"""Executed by FreeCADCmd's bundled Python, not the MCP host's Python."""

import json
import os
import sys
import traceback


def run():
    import FreeCAD

    source = os.environ["CAD_MCP_SOURCE"]
    action = os.environ["CAD_MCP_ACTION"]
    result_path = os.environ["CAD_MCP_RESULT"]
    doc = FreeCAD.openDocument(source)
    try:
        objects = []
        for obj in doc.Objects:
            if not hasattr(obj, "Shape") or obj.Shape.isNull():
                continue
            box = obj.Shape.BoundBox
            objects.append({
                "name": obj.Name,
                "label": obj.Label,
                "type_id": obj.TypeId,
                "volume_mm3": obj.Shape.Volume,
                "bounds_mm": [box.XLength, box.YLength, box.ZLength],
                "valid": obj.Shape.isValid(),
            })
        result = {"objects": objects}
        if action == "export":
            name = os.environ["CAD_MCP_OBJECT"]
            target = os.environ["CAD_MCP_TARGET"]
            obj = doc.getObject(name)
            if obj is None or not hasattr(obj, "Shape") or obj.Shape.isNull():
                raise ValueError("Object has no usable shape: " + name)
            if not obj.Shape.isValid():
                raise ValueError("Object shape is invalid: " + name)
            import MeshPart

            mesh = MeshPart.meshFromShape(Shape=obj.Shape, LinearDeflection=0.10,
                                          AngularDeflection=0.35, Relative=False)
            mesh.write(target)
            result["exported"] = {"object": name, "stl_path": target,
                                  "facets": mesh.CountFacets}
        with open(result_path, "w", encoding="utf-8") as handle:
            json.dump({"ok": True, "result": result}, handle)
    finally:
        FreeCAD.closeDocument(doc.Name)


try:
    run()
except Exception:
    with open(os.environ["CAD_MCP_RESULT"], "w", encoding="utf-8") as handle:
        json.dump({"ok": False, "error": traceback.format_exc()}, handle)
    sys.exit(1)
