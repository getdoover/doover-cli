class Dummy:
    def test(self):
        print("tested")

class Test:
    def __init__(self):
        self.ctx = 2
        self._api = None

    def __call__(self, *args, **kwargs):
        print("Test called with args:", args, "and kwargs:", kwargs)
        return True

    def __getattr__(self, item):
        if item == "ctx":
            return self.ctx

        if self._api is None:
            print("creating api")
            self._api = Dummy()

        return getattr(self._api, item)

x = Test()
x.test()
