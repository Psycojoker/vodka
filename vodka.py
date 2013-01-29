import _ast
import ast

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
            self.model[assign_node.targets[0].id] = assign_node.value.s
        if assign_node.targets[0].id == "_columns":
            self.model[assign_node.targets[0].id] = map(lambda x: x.s, assign_node.value.keys)

    def visit_FunctionDef(self, _):
        pass

def get_classes_from_string(string):
    class_finder = ClassFinder()
    class_finder.visit(ast.parse(string))
    return class_finder.models
