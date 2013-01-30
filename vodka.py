import os
import _ast
import ast
from ConfigParser import ConfigParser
from path import path


def parse_attr(attr):
    to_return = []
    while isinstance(attr, _ast.Attribute):
        to_return.append(attr.attr)
        attr = attr.value
    to_return.append(attr.id)  # assume we are a Name
    return ".".join(reversed(to_return))

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
        if assign_node.targets[0].id == "_columns":
            self.model[assign_node.targets[0].id] = self.parse_columns(assign_node.value)

    def visit_FunctionDef(self, _):
        pass

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
            to_return.append(row)
        return to_return

    def handle_generic(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                row["string"] = parse_gettext(arg)
            else:
                raise

    def handle_one2many(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("model"):
                row["model"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("field"):
                row["field"] = parse_gettext(arg)
            elif isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("string"):
                row["string"] = parse_gettext(arg)
            else:
                raise

    def handle_many2one(self, args, row):
        for arg in args:
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("model"):
                row["model"] = parse_gettext(arg)
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
            if isinstance(arg, (_ast.Str, _ast.Call)) and not row.get("model"):
                row["model"] = parse_gettext(arg)
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


def get_classes_from_config_file(config_path="~/.openerp_serverrc"):
    addons = {}
    config_parser = ConfigParser()
    config_parser.readfp(open(os.path.expanduser(config_path)))
    addons_folders = map(lambda x: x.strip(), config_parser.get("options", "addons_path").split(","))
    for addons_folder in addons_folders:
        addons_folder = path(addons_folder)
        for addon in addons_folder.dirs():
            addons[addon.name] = {}
            for python_file in addon.walk("*.py"):
                if python_file.name.startswith("_"):
                    continue
                addons[addon.name].update(get_classes_from_string(open(python_file).read()))

    from ipdb import set_trace; set_trace()
    print addons


if __name__ == '__main__':
    get_classes_from_config_file()
    #a = get_classes_from_string(open("/home/psycojoker/railnova/railfleet-modules/railfleet_maintenance_alstom/maintenance.py").read())
    #from pprint import pprint
    #pprint(a)
    #from ipdb import set_trace; set_trace()
