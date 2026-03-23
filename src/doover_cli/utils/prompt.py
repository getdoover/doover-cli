import click
import questionary
import typer
from typing import cast


class QuestionaryPrompt(click.Option):
    """A custom click option that uses questionary for prompting the user."""

    def prepare_choice_list(self, ctx):
        default = self.get_default(ctx) or []
        choice_type = cast(click.Choice, self.type)
        return [
            questionary.Choice(name, checked=name in default)
            for name in choice_type.choices
        ]

    def prompt_for_value(self, ctx: click.Context):
        prompt = self.prompt or ""
        default = self.get_default(ctx)

        if isinstance(self.type, click.Choice):
            choice_type = cast(click.Choice, self.type)
            if len(self.type.choices) == 1:
                return self.type.choices[0]
            if self.multiple:
                return questionary.checkbox(
                    prompt, choices=self.prepare_choice_list(ctx)
                ).unsafe_ask()
            else:
                return questionary.select(
                    prompt,
                    choices=choice_type.choices,
                    default=default,
                ).unsafe_ask()
        if isinstance(self.type, click.types.StringParamType):
            if self.hide_input is True:
                return questionary.password(
                    prompt,
                    default=str(default) if default is not None else "",
                ).unsafe_ask()
            return questionary.text(
                prompt,
                default=str(default) if default is not None else "",
            ).unsafe_ask()

        if isinstance(self.type, click.types.BoolParamType):
            return questionary.confirm(
                prompt,
                default=bool(default) if default is not None else False,
            ).unsafe_ask()

        return super().prompt_for_value(ctx)


class TextPrompt(click.Option):
    def prompt_for_value(self, ctx):
        prompt = self.prompt or ""
        default = self.get_default(ctx)
        return questionary.text(
            prompt,
            default=str(default) if default is not None else "",
        ).unsafe_ask()


class QuestionaryPromptCommand(typer.main.TyperCommand):
    """Class to allow interoperability between typer option prompts and questionary for "nice" prompting."""

    def __init__(self, *args, **kwargs):
        for p in kwargs.get("params", []):
            if isinstance(p, click.Option):
                p.__class__ = QuestionaryPrompt
        super().__init__(*args, **kwargs)
