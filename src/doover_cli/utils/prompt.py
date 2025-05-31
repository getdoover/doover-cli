import click
import questionary
import typer


class QuestionaryPrompt(click.Option):
    """A custom click option that uses questionary for prompting the user."""

    def prepare_choice_list(self, ctx):
        default = self.get_default(ctx) or []
        return [questionary.Choice(n, checked=n in default) for n in self.type.choices]

    def prompt_for_value(self, ctx: click.Context):
        if isinstance(self.type, click.Choice):
            if len(self.type.choices) == 1:
                return self.type.choices[0]
            if self.multiple:
                return questionary.checkbox(
                    self.prompt, choices=self.prepare_choice_list(ctx)
                ).unsafe_ask()
            else:
                return questionary.select(
                    self.prompt,
                    choices=self.type.choices,
                    default=self.get_default(ctx),
                ).unsafe_ask()
        if isinstance(self.type, click.types.StringParamType):
            if self.hide_input is True:
                return questionary.password(
                    self.prompt,
                    default=str(
                        self.get_default(ctx)
                        if self.get_default(ctx) is not None
                        else ""
                    ),
                ).unsafe_ask()
            return questionary.text(
                self.prompt,
                default=str(
                    self.get_default(ctx) if self.get_default(ctx) is not None else ""
                ),
            ).unsafe_ask()

        if isinstance(self.type, click.types.BoolParamType):
            return questionary.confirm(
                self.prompt,
                default=self.get_default(ctx)
                if self.get_default(ctx) is not None
                else False,
            ).unsafe_ask()

        return super().prompt_for_value(ctx)


class TextPrompt(click.Option):
    def prompt_for_value(self, ctx):
        return questionary.text(
            self.prompt,
            default=str(
                self.get_default(ctx) if self.get_default(ctx) is not None else ""
            ),
        ).unsafe_ask()


class QuestionaryPromptCommand(typer.main.TyperCommand):
    """Class to allow interoperability between typer option prompts and questionary for "nice" prompting."""

    def __init__(self, *args, **kwargs):
        for p in kwargs.get("params", []):
            if isinstance(p, click.Option):
                p.__class__ = QuestionaryPrompt
        super().__init__(*args, **kwargs)
