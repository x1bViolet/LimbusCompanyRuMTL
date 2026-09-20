from scripts.json_data import JsonValue

class JSONPath:
    def find(self, data: JsonValue) -> list[DatumInContext]: ...
    def update(self, data: JsonValue, val: JsonValue) -> JsonValue: ...

class DatumInContext:
    value: JsonValue
    @property
    def full_path(self) -> JSONPath: ...
