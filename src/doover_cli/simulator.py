from typer import Typer

app = Typer(no_args_is_help=True)

@app.command()
def create():
    pass

@app.command()
def run():
    pass

@app.command()
def deploy():
    pass

@app.command()
def test():
    pass
