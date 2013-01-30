import os
import json
from vodka import get_classes_from_config_file

if __name__ == '__main__':
    #open("db.json", "w").write(json.dumps(get_classes_from_config_file(), indent=4))
    string = "digraph G {\n"
    db = json.load(open("db.json"))
    to_write = []
    relations = []
    for key, module in db.items():
        #if not key.startswith("railfleet"):
            #continue
        if key not in ("railfleet", "railfleet_maintenance", "railfleet_maintenance_alstom"):
            continue
        to_write.append('subgraph cluster%s {\nlabel="%s"' % (key.replace(" ", ""), key))
        for class_name, data in module.items():
            #print classes
            #from ipdb import set_trace; set_trace()
            if not data.get("_inherit"):
                to_write.append('"%s" [\nshape="record"\nlabel="{%s |%s}"]' % (data.get("_name", class_name), data.get("_name", class_name), "|".join(map(lambda x: x.get("name", ""), data.get("_columns", [])))))
            else:
                to_write.append('"%s [%s]" [\nshape="record"\nlabel="{%s [%s] |%s}"]' % (data.get("_name", class_name), key, data.get("_name", class_name), "|".join(map(lambda x: x.get("name", ""), data.get("_columns", []))), key))
                relations.append('"%s" -> "%s"' % (data.get("_name", class_name), data["_inherit"]))
            for field in data.get("_columns", []):
                if field["type"] in ("many2one", "many2many"):
                    relation = '"%s" -> "%s"' % (field["relation"], data.get("_name", class_name))
                    if relation not in relations:
                        relations.append(relation)

        to_write.append("}")

    string += ";\n".join(to_write)
    string += ";\n".join(relations)
    #string += ";\n".join(set(to_write))
    string += "};"

    #print string
    open("qsd.dot", "w").write(string)
    os.system("dot -Tpng qsd.dot > qsd.png")
