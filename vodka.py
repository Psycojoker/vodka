# Vodka is a lib that extract OpenERP models informations
# Copyright (C) 2013  Laurent Peuch <cortex@worlddomination.be>
# Copyright (C) 2013  Railnova SPRL <railnova@railnova.eu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import _ast
import ast
import subprocess
from ConfigParser import ConfigParser
from path import path

from BeautifulSoup import BeautifulStoneSoup

def format_xml(to_write):
    xmllint_is_installed = subprocess.Popen(['which', 'xmllint'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()[0]
    if not xmllint_is_installed:
        return to_write

    formated, err = subprocess.Popen(['xmllint', '--format', '/dev/stdin'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate(to_write)
    if not err:
        # remove <?xml ...> stuff
        to_write = "\n".join(formated.split("\n")[1:])
    return to_write

def parse_attr(attr):
    to_return = []
    while isinstance(attr, _ast.Attribute):
        to_return.append(attr.attr)
        attr = attr.value
    to_return.append(get_value(attr))
    return ".".join(reversed(to_return))


def get_value(elt):
    if isinstance(elt, _ast.Num):
        return elt.n
    elif isinstance(elt, _ast.Name):
        return elt.id
    elif isinstance(elt, _ast.Str):
        return elt.s
    elif isinstance(elt, (_ast.List, _ast.Tuple)):
        return map(get_value, elt.elts)
    elif isinstance(elt, _ast.Dict):
        return dict(zip(map(get_value, elt.keys), map(get_value, elt.values)))
    elif isinstance(elt, _ast.Lambda):
        return "lambda"
    elif isinstance(elt, _ast.Call) and isinstance(elt.func, _ast.Name):
        # TODO: handle keywords
        return "%s(%s)" % (elt.func.id, map(get_value, elt.args) if elt.args else "")
    elif isinstance(elt, _ast.Call):
        return parse_attr(elt.func)
    elif isinstance(elt, _ast.Attribute):
        return parse_attr(elt)
    elif isinstance(elt, _ast.BinOp) and isinstance(elt.op, _ast.Add):
        return parse_attr(elt.left) + parse_attr(elt.right)
    else:
        raise Exception(elt)

def parse_gettext(string_or_call):
    if isinstance(string_or_call, _ast.Str):
        return string_or_call.s
    elif isinstance(string_or_call, _ast.Call):
        if string_or_call.func.id not in ("_", "gettext", "translate"):
            raise Exception("was expecting a gettext call, got '%s' instead" % string_or_call.func.id)
        return string_or_call.args[0].s
    elif isinstance(string_or_call, _ast.Num):
        return string_or_call.n
    else:
        raise ValueError("parse_gettext is expecting either a _ast.Str or a _ast.Call")

class ClassFinder(ast.NodeVisitor):
    def __init__(self):
        self.models = {}

    def is_oerp_mode(self, class_node):
        for i in class_node.bases:
            if isinstance(i, _ast.Name) and i.id == "osv":
                return True
            if isinstance(i, _ast.Attribute) and i.attr == "osv" and i.value.id == "osv":
                return True

        return False

    def visit_ClassDef(self, class_node):
        if not self.is_oerp_mode(class_node):
            return
        self.models[class_node.name] = {"class_name": class_node.name}
        self.models[class_node.name]["lineno"] = {"class": class_node.lineno}
        self.models[class_node.name]["methods"] = []
        KeyAttributesFinder(self.models[class_node.name]).visit(class_node)


class KeyAttributesFinder(ast.NodeVisitor):
    def __init__(self, model):
        self.model = model

    def visit_Assign(self, assign_node):
        if assign_node.targets[0].id in ("_name", "_inherit"):
            if isinstance(assign_node.value, _ast.List):
                value = map(lambda x: x.s, assign_node.value.elts)
                self.model[assign_node.targets[0].id] = value if len(value) > 1 else value[0]
            else:
                self.model[assign_node.targets[0].id] = assign_node.value.s
            if assign_node.targets[0].id == "_inherit" and not self.model.has_key("_name"):
                self.model["_name"] = self.model["_inherit"]
        if assign_node.targets[0].id == "_columns":
            self.model[assign_node.targets[0].id] = self.parse_columns(assign_node.value)
            self.model["lineno"]["_columns"] = assign_node.lineno

    def visit_FunctionDef(self, function_node):
        self.model["methods"].append({
            "name": function_node.name,
            "lineno": function_node.lineno,
            "args": map(lambda x: get_value(x), function_node.args.args),
            "defaults": map(lambda x: get_value(x), function_node.args.defaults),
            "kwarg": function_node.args.kwarg,
            "vararg": function_node.args.vararg,
        })

    def parse_columns(self, columns):
        handle_args = {
            "one2many": self.handle_one2many,
            "many2one": self.handle_many2one,
            "many2many": self.handle_many2many,
            "selection": self.handle_selection,
            "function": self.handle_function,
            "related": self.handle_related,
        }
        to_return = []
        for key, value in zip(columns.keys, columns.values):
            row = {"name": key.s}

            if isinstance(getattr(value, "func", None), _ast.Name):  # for ppl that overwrite fields class
                row["type"] = value.func.id
                continue
            elif not hasattr(value, "func"):  # drop hacks from other ppl
                continue

            row["type"] = value.func.attr
            handle_args.get(row["type"], self.handle_generic)(value.args, row)
            for kwarg in value.keywords:
                row[kwarg.arg] = get_value(kwarg.value)
            to_return.append(row)
        return to_return

    def handle_generic(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                try:
                    row["string"] = unicode(parse_gettext(arg))
                except UnicodeDecodeError:
                    pass
                try:
                    row["string"] = parse_gettext(arg).decode("Utf-8")
                except UnicodeEncodeError:
                    pass
                row["string"] = parse_gettext(arg)
            else:
                raise

    def handle_one2many(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("relation"):
                row["relation"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("field"):
                row["field"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                row["string"] = parse_gettext(arg)
            else:
                raise

    def handle_many2one(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("relation"):
                row["relation"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                row["string"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)):
                raise
            else:
                raise

    def handle_selection(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.List, _ast.Tuple)):
                row["selection"] = map(lambda x: [parse_gettext(x.elts[0]), parse_gettext(x.elts[1])], arg.elts)
                row["is_function"] = False
            elif isinstance(arg, _ast.Name):
                row["selection"] = arg.id
                row["is_function"] = True
            elif isinstance(arg, _ast.Attribute):
                row["selection"] = parse_attr(arg)
                row["is_function"] = True
            elif isinstance(arg, _ast.Call) and not row.get("selection") and (not isinstance(arg.func, _ast.Name) or arg.func.id not in ("_", "gettext", "translate")):
                row["selection"] = parse_attr(arg.func)
                row["is_function"] = True
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                row["string"] = parse_gettext(arg)
            else:
                raise

    def handle_function(self, args, row):
        for arg in args:
            if isinstance(arg, _ast.Name):
                row["function"] = arg.id
            elif isinstance(arg, _ast.Attribute):
                row["function"] = parse_attr(arg)
            elif isinstance(arg, _ast.Lambda):
                row["function"] = "lambda"
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                row["string"] = parse_gettext(arg)
            else:
                raise

    def handle_many2many(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("relation"):
                row["relation"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("relation_table"):
                row["relation_table"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("field1"):
                row["field1"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("field2"):
                row["field2"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                row["string"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)):
                raise
            else:
                raise

    def handle_related(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("relation"):
                row["relation"] = [parse_gettext(arg)]
            elif isinstance(arg, (_ast.Str, _ast.Call)):
                row["relation"].append(parse_gettext(arg))
            else:
                raise


def get_classes_from_string(string):
    class_finder = ClassFinder()
    class_finder.visit(ast.parse(string))
    return class_finder.models


def get_views_from_string(string):
    def get_field(view, name, default=None):
        # stupid bug in BS, you can't search on 'name=' since name is the
        # keyword for tag_name
        field_model = filter(lambda x: x.get('name') == name, view('field', recursive=False))
        if field_model:
            return field_model[0]
        return default

    soup = BeautifulStoneSoup(string)
    xml = {"views": {}, "actions": {}}
    if not soup.openerp or not soup.openerp.data:
        return xml

    for view in soup.openerp.data("record"):
        if not view.get("id"):
            continue
        if view.get("model") == 'ir.ui.view':
            field_model = get_field(view, "model")
            if field_model is None:
                continue

            xml["views"][view["id"]] = {"model": field_model.text, "string": format_xml(str(view))}

        elif view.get("model") == "ir.actions.act_window":
            field_model = get_field(view, "res_model")
            if field_model is None:
                continue
            xml["actions"][view["id"]] = {"model": field_model.text, "string": format_xml(str(view))}
            if get_field(view, "view_type"):
                xml["actions"][view["id"]]["view_type"] = get_field(view, "view_type").text
            if get_field(view, "view_mode"):
                xml["actions"][view["id"]]["view_mode"] = get_field(view, "view_mode").text

    return xml

def get_classes_from_config_file(config_path="~/.openerp_serverrc"):
    addons = {}
    config_parser = ConfigParser()
    config_parser.readfp(open(os.path.expanduser(config_path)))
    addons_folders = map(lambda x: x.strip(), config_parser.get("options", "addons_path").split(","))
    for addons_folder in addons_folders:
        addons_folder = path(addons_folder)
        for addon in addons_folder.dirs():
            addons[addon.name] = {}
            if addon.joinpath("__openerp__.py").exists():
                addons[addon.name]["__openerp__"] = eval(open(addon.joinpath("__openerp__.py"), "r").read())
            elif addon.joinpath("__terp__.py").exists():
                addons[addon.name]["__openerp__"] = eval(open(addon.joinpath("__terp__.py"), "r").read())
            else:
                del addons[addon.name]
                continue

            for python_file in addon.walk("*.py"):
                if python_file.name.startswith("_"):
                    continue
                models = get_classes_from_string(open(python_file).read())
                for model in models.keys():
                    models[model]["file"] = python_file
                addons[addon.name].setdefault("models", {}).update(models)

            for xml_file in addon.walk("*.xml"):
                xml = get_views_from_string(open(xml_file, "r").read())
                addons[addon.name].setdefault("xml", {}).setdefault("views", {}).update(xml["views"])
                addons[addon.name].setdefault("xml", {}).setdefault("actions", {}).update(xml["actions"])

    return addons


if __name__ == '__main__':
    get_classes_from_config_file()
    #a = get_classes_from_string(open("/home/psycojoker/railnova/railfleet-modules/railfleet_maintenance_alstom/maintenance.py").read())
    #from pprint import pprint
    #pprint(a)
    #from ipdb import set_trace; set_trace()
