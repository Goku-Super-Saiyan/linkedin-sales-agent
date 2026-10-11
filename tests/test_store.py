from agent.store import HEADERS, PENDING, PostRow, SheetStore


class FakeWorksheet:
    def __init__(self):
        self.cells = [list(HEADERS.values())]

    def get_all_values(self):
        return [list(r) for r in self.cells]

    def append_row(self, values, table_range=None):
        self.cells.append(list(values))

    def update(self, values, a1):
        col = ord(a1[0]) - ord("A")
        row = int(a1[1:]) - 1
        self.cells[row][col] = values[0][0]


def sheet_store():
    store = SheetStore.__new__(SheetStore)
    store.ws = FakeWorksheet()
    return store


def test_sheet_store_round_trip_and_update():
    store = sheet_store()
    store.add_post(PostRow("p1", "2026-10-11", PENDING, "Topic", "Text"))
    store.add_post(PostRow("p2", "2026-10-12", PENDING, "Topic 2", "Text 2"))
    store.update_post("p2", status="Approved", notes="ok")
    rows = store.list_posts()
    assert [r.id for r in rows] == ["p1", "p2"]
    assert rows[1].status == "Approved" and rows[1].notes == "ok"
    assert rows[0].status == PENDING


def test_sheet_store_tolerates_short_and_blank_rows():
    store = sheet_store()
    store.ws.cells.append(["p1", "2026-10-11", "Approved"])
    store.ws.cells.append(["", "", ""])
    rows = store.list_posts()
    assert len(rows) == 1 and rows[0].text == ""
