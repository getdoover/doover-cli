import importlib
import os
import shutil
from datetime import timezone, datetime, timedelta

from typing_extensions import Annotated

from typer import Argument, Typer

from .utils.context import Context

app = Typer(no_args_is_help=True)


@app.command()
def compose_report(
    ctx: Context,
    period_from: Annotated[
        datetime, Argument(help="Start of the period to report on")
    ] = datetime.now() - timedelta(days=7),
    period_to: Annotated[
        datetime, Argument(help="End of the period to report on")
    ] = None,
    agent_ids: Annotated[str, Argument(help="Agent IDs to run the report on")] = "",
    agent_names: Annotated[
        str, Argument(help="Agent display names to run the report on")
    ] = "",
    package_path: Annotated[
        str, Argument(help="Path to the python report generator module to compose")
    ] = "pydoover.reports.xlsx_base",
):
    """
    Compose a report locally.

    Example Usage:
    pydoover compose_report --agent_ids "abcdefg,abdfgds" --agent_names "Agent 1,Agent 2"
    """

    if isinstance(agent_ids, str):
        agent_ids = agent_ids.split(",")
    if isinstance(agent_names, str):
        agent_names = agent_names.split(",")

    ## Attempt necessary imports
    import pytz
    import tzlocal

    module = importlib.import_module(package_path)

    # Retrieve the report generator class from the imported module.
    # Here we assume the class is named "Generator". Adjust if necessary.
    ReportGeneratorClass = getattr(module, "generator", None)
    if ReportGeneratorClass is None:
        print("No 'Generator' found in the specified module!")
        return

    # If period_to is not provided, default to now.
    if period_to is None:
        period_to = datetime.now(timezone.utc)

    # Define additional parameters for instantiation.
    tmp_workspace = "/tmp/doover_report_output/"  # Adjust as needed
    access_token = ctx.config_manager.current.token  # Provide valid access token
    api_endpoint = ctx.config_manager.current.base_url  # Provide valid endpoint
    report_name = "Local Report"
    test_mode = False  # Set as needed

    # Clear and recreate the temporary workspace.
    if os.path.exists(tmp_workspace):
        shutil.rmtree(tmp_workspace)
    os.makedirs(tmp_workspace)

    # Get the local timezone as a pytz object
    local_tz_name = tzlocal.get_localzone_name()
    for_timezone = pytz.timezone(local_tz_name)

    def progress_update(progress: int):
        if progress is not None:
            print(f"Progress: {progress * 100}%")

    # Instantiate the report generator.
    report_instance = ReportGeneratorClass(
        tmp_workspace=tmp_workspace,
        access_token=access_token,
        agent_ids=agent_ids,
        agent_display_names=agent_names,
        period_from_utc=period_from.astimezone(timezone.utc),
        period_to_utc=period_to.astimezone(timezone.utc),
        for_timezone=for_timezone,
        logging_function=print,
        progress_update_function=progress_update,
        api_endpoint=api_endpoint,
        report_name=report_name,
        test_mode=test_mode,
    )

    # Invoke the report generation.
    report_instance.generate()
    print("Report composed successfully!")
    print(f"Output saved to: {tmp_workspace}")
