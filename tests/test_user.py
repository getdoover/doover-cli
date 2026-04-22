import re
from contextlib import nullcontext
from types import SimpleNamespace

from pydoover.models.control import Organisation
from typer.testing import CliRunner

from doover_cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _resource_methods(**kwargs):
    return SimpleNamespace(**kwargs)


class FakeRenderer:
    def __init__(self, prompt_answers=None):
        self.prompt_answers = prompt_answers or {}
        self.prompt_fields_calls = []
        self.render_calls = []
        self.render_list_calls = []

    def loading(self, _message):
        return nullcontext()

    def prompt_fields(self, fields):
        self.prompt_fields_calls.append(fields)
        return {
            field.key: self.prompt_answers.get(field.key, field.default)
            for field in fields
        }

    def render(self, data):
        self.render_calls.append(data)

    def render_list(self, data):
        self.render_list_calls.append(data)


class FakeUsersClient:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"results": []}

    def retrieve(self, user_id):
        self.calls.append(("retrieve", user_id))
        return {"id": int(user_id)}

    def me(self):
        self.calls.append(("me",))
        return {"id": 7, "email": "me@example.com"}

    def partial(self, user_id, body=None):
        self.calls.append(("partial", user_id, body))
        return {"id": int(user_id), **(body or {})}

    def sync(self, user_id, body=None):
        self.calls.append(("sync", user_id, body))
        return {"id": int(user_id), "synced": True, **(body or {})}


class FakeOrganisationUsersClient:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"results": []}

    def retrieve(self, user, organisation_id=None):
        self.calls.append(("retrieve", user, organisation_id))
        return {"user": user}

    def create(self, body, organisation_id=None):
        self.calls.append(("create", body, organisation_id))
        return {"created": True, **body}

    def partial(self, user, body=None, organisation_id=None):
        self.calls.append(("partial", user, body, organisation_id))
        return {"user": user, **(body or {})}

    def delete(self, user, organisation_id=None):
        self.calls.append(("delete", user, organisation_id))

    def groups_list(self, **kwargs):
        self.calls.append(("groups_list", kwargs))
        return {"results": []}


class FakePendingUsersClient:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"results": []}

    def retrieve(self, pending_user_id, organisation_id=None):
        self.calls.append(("retrieve", pending_user_id, organisation_id))
        return {"id": int(pending_user_id)}

    def create(self, body, organisation_id=None):
        self.calls.append(("create", body, organisation_id))
        return {"created": True, **body}

    def approve(self, pending_user_id, body, organisation_id=None):
        self.calls.append(("approve", pending_user_id, body, organisation_id))
        return {"id": int(pending_user_id), "approved": True}

    def reject(self, pending_user_id, body, organisation_id=None):
        self.calls.append(("reject", pending_user_id, body, organisation_id))
        return {"id": int(pending_user_id), "rejected": True}

    def delete(self, pending_user_id, organisation_id=None):
        self.calls.append(("delete", pending_user_id, organisation_id))


class FakeRolesClient:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"results": []}

    def retrieve(self, role_id, organisation_id=None):
        self.calls.append(("retrieve", role_id, organisation_id))
        return {"id": int(role_id)}


def _org_page(organisations):
    return SimpleNamespace(
        results=[SimpleNamespace(id=org_id, name=name) for org_id, name in organisations],
        next=None,
        count=len(organisations),
    )


def _fake_state(monkeypatch, organisations=None, prompt_answers=None):
    renderer = FakeRenderer(prompt_answers=prompt_answers)
    users = FakeUsersClient()
    org_users = FakeOrganisationUsersClient()
    pending_users = FakePendingUsersClient()
    roles = FakeRolesClient()
    organisations = organisations or [(17, "Acme")]

    class FakeControlClient:
        def __init__(self):
            self.users = users
            self.organisations = SimpleNamespace(
                users=org_users,
                pending_users=pending_users,
                roles=roles,
            )

        def get_control_methods(self, model_cls):
            if model_cls is Organisation:
                return _resource_methods(
                    list=lambda **kwargs: _org_page(organisations),
                )
            raise AssertionError(f"Unexpected model lookup: {model_cls}")

    monkeypatch.setattr(
        "doover_cli.user.get_state",
        lambda: (FakeControlClient(), renderer),
    )
    return renderer, users, org_users, pending_users, roles


def test_help_lists_org_and_users_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    output = _strip_ansi(result.stdout)
    assert "org" in output
    assert "users" in output


def test_users_list_passes_filters(monkeypatch):
    renderer, users, _, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        ["users", "list", "--ordering", "email", "--page", "2", "--per-page", "25", "--search", "tom"],
    )

    assert result.exit_code == 0
    assert users.calls == [
        (
            "list",
            {
                "ordering": "email",
                "page": 2,
                "per_page": 25,
                "search": "tom",
            },
        )
    ]
    assert renderer.render_list_calls == [{"results": []}]


def test_users_get_renders_response(monkeypatch):
    renderer, users, _, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(app, ["users", "get", "42"])

    assert result.exit_code == 0
    assert users.calls == [("retrieve", "42")]
    assert renderer.render_calls == [{"id": 42}]


def test_users_me_renders_response(monkeypatch):
    renderer, users, _, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(app, ["users", "me"])

    assert result.exit_code == 0
    assert users.calls == [("me",)]
    assert renderer.render_calls == [{"id": 7, "email": "me@example.com"}]


def test_users_update_patches_custom_data(monkeypatch):
    renderer, users, _, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        ["users", "update", "42", "--custom-data", '{"theme":"dark"}'],
    )

    assert result.exit_code == 0
    assert users.calls == [("partial", "42", {"custom_data": {"theme": "dark"}})]
    assert renderer.render_calls == [{"id": 42, "custom_data": {"theme": "dark"}}]


def test_users_sync_posts_custom_data(monkeypatch):
    renderer, users, _, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        ["users", "sync", "42", "--custom-data", '{"theme":"dark"}'],
    )

    assert result.exit_code == 0
    assert users.calls == [("sync", "42", {"custom_data": {"theme": "dark"}})]
    assert renderer.render_calls == [
        {"id": 42, "synced": True, "custom_data": {"theme": "dark"}}
    ]


def test_org_users_list_passes_explicit_org(monkeypatch):
    renderer, _, org_users, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "org",
            "users",
            "list",
            "Acme",
            "--ordering",
            "email",
            "--page",
            "2",
            "--per-page",
            "25",
            "--search",
            "tom",
        ],
    )

    assert result.exit_code == 0
    assert org_users.calls == [
        (
            "list",
            {
                "ordering": "email",
                "page": 2,
                "per_page": 25,
                "search": "tom",
                "organisation_id": 17,
            },
        )
    ]
    assert renderer.render_list_calls == [{"results": []}]


def test_org_users_list_assumes_single_org_when_omitted(monkeypatch):
    _, _, org_users, _, _ = _fake_state(monkeypatch, organisations=[(17, "Acme")])

    result = runner.invoke(app, ["org", "users", "list"])

    assert result.exit_code == 0
    assert org_users.calls == [
        (
            "list",
            {
                "ordering": None,
                "page": None,
                "per_page": None,
                "search": None,
                "organisation_id": 17,
            },
        )
    ]


def test_org_users_list_prompts_when_multiple_orgs(monkeypatch):
    renderer, _, org_users, _, _ = _fake_state(
        monkeypatch,
        organisations=[(17, "Acme"), (18, "Beta")],
        prompt_answers={"resource_id": "Beta (18)"},
    )

    result = runner.invoke(app, ["org", "users", "list"])

    assert result.exit_code == 0
    assert len(renderer.prompt_fields_calls) == 1
    assert org_users.calls == [
        (
            "list",
            {
                "ordering": None,
                "page": None,
                "per_page": None,
                "search": None,
                "organisation_id": 18,
            },
        )
    ]


def test_org_users_get_renders_response(monkeypatch):
    renderer, _, org_users, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(app, ["org", "users", "get", "Acme", "alice@example.com"])

    assert result.exit_code == 0
    assert org_users.calls == [("retrieve", "alice@example.com", 17)]
    assert renderer.render_calls == [{"user": "alice@example.com"}]


def test_org_users_add_creates_membership(monkeypatch):
    renderer, _, org_users, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "org",
            "users",
            "add",
            "Acme",
            "alice@example.com",
            "--role-id",
            "7",
            "--add-to-group",
            "11:12",
            "--add-to-group",
            '{"group_id": 13, "role_id": 14}',
        ],
    )

    assert result.exit_code == 0
    assert org_users.calls == [
        (
            "create",
            {
                "user_email": "alice@example.com",
                "role_id": 7,
                "add_to_group": [
                    {"group_id": 11, "role_id": 12},
                    {"group_id": 13, "role_id": 14},
                ],
            },
            17,
        )
    ]
    assert renderer.render_calls == [
        {
            "created": True,
            "user_email": "alice@example.com",
            "role_id": 7,
            "add_to_group": [
                {"group_id": 11, "role_id": 12},
                {"group_id": 13, "role_id": 14},
            ],
        }
    ]


def test_org_users_update_patches_membership(monkeypatch):
    renderer, _, org_users, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "org",
            "users",
            "update",
            "Acme",
            "alice@example.com",
            "--email",
            "alice+updated@example.com",
            "--role-id",
            "8",
        ],
    )

    assert result.exit_code == 0
    assert org_users.calls == [
        (
            "partial",
            "alice@example.com",
            {"user_email": "alice+updated@example.com", "role_id": 8},
            17,
        )
    ]
    assert renderer.render_calls == [
        {
            "user": "alice@example.com",
            "user_email": "alice+updated@example.com",
            "role_id": 8,
        }
    ]


def test_org_users_remove_deletes_membership(monkeypatch):
    renderer, _, org_users, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        ["org", "users", "remove", "Acme", "alice@example.com"],
    )

    assert result.exit_code == 0
    assert org_users.calls == [("delete", "alice@example.com", 17)]
    assert renderer.render_calls == [{"removed": True, "user": "alice@example.com"}]


def test_org_users_groups_passes_filters(monkeypatch):
    renderer, _, org_users, _, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "org",
            "users",
            "groups",
            "Acme",
            "alice@example.com",
            "--ordering",
            "group",
            "--page",
            "2",
            "--per-page",
            "50",
            "--search",
            "ops",
        ],
    )

    assert result.exit_code == 0
    assert org_users.calls == [
        (
            "groups_list",
            {
                "parent_lookup_user": "alice@example.com",
                "ordering": "group",
                "page": 2,
                "per_page": 50,
                "search": "ops",
                "organisation_id": 17,
            },
        )
    ]
    assert renderer.render_list_calls == [{"results": []}]


def test_org_users_pending_list_and_get(monkeypatch):
    renderer, _, _, pending_users, _ = _fake_state(monkeypatch)

    list_result = runner.invoke(
        app,
        [
            "org",
            "users",
            "pending",
            "list",
            "Acme",
            "--ordering",
            "email",
            "--page",
            "2",
            "--per-page",
            "25",
            "--search",
            "tom",
        ],
    )
    get_result = runner.invoke(
        app,
        ["org", "users", "pending", "get", "Acme", "9"],
    )

    assert list_result.exit_code == 0
    assert get_result.exit_code == 0
    assert pending_users.calls == [
        (
            "list",
            {
                "ordering": "email",
                "page": 2,
                "per_page": 25,
                "search": "tom",
                "organisation_id": 17,
            },
        ),
        ("retrieve", "9", 17),
    ]
    assert renderer.render_list_calls == [{"results": []}]
    assert renderer.render_calls == [{"id": 9}]


def test_org_users_pending_add_creates_record(monkeypatch):
    renderer, _, _, pending_users, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "org",
            "users",
            "pending",
            "add",
            "Acme",
            "alice@example.com",
            "--message",
            "Welcome",
        ],
    )

    assert result.exit_code == 0
    assert pending_users.calls == [
        (
            "create",
            {
                "email": "alice@example.com",
                "organisation_id": 17,
                "message": "Welcome",
            },
            17,
        )
    ]
    assert renderer.render_calls == [
        {
            "created": True,
            "email": "alice@example.com",
            "organisation_id": 17,
            "message": "Welcome",
        }
    ]


def test_org_invite_creates_pending_user(monkeypatch):
    renderer, _, _, pending_users, _ = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        ["org", "invite", "Acme", "alice@example.com", "--message", "Welcome"],
    )

    assert result.exit_code == 0
    assert pending_users.calls == [
        (
            "create",
            {
                "email": "alice@example.com",
                "organisation_id": 17,
                "message": "Welcome",
            },
            17,
        )
    ]
    assert renderer.render_calls == [
        {
            "created": True,
            "email": "alice@example.com",
            "organisation_id": 17,
            "message": "Welcome",
        }
    ]


def test_org_invite_prompts_for_missing_email(monkeypatch):
    renderer, _, _, pending_users, _ = _fake_state(
        monkeypatch,
        prompt_answers={"email": "alice@example.com", "message": ""},
    )

    result = runner.invoke(app, ["org", "invite"])

    assert result.exit_code == 0
    assert len(renderer.prompt_fields_calls) == 2
    assert pending_users.calls == [
        (
            "create",
            {
                "email": "alice@example.com",
                "organisation_id": 17,
            },
            17,
        )
    ]
    assert renderer.render_calls == [
        {
            "created": True,
            "email": "alice@example.com",
            "organisation_id": 17,
        }
    ]


def test_org_users_pending_approve_reject_and_delete(monkeypatch):
    renderer, _, _, pending_users, _ = _fake_state(monkeypatch)

    approve_result = runner.invoke(
        app,
        ["org", "users", "pending", "approve", "Acme", "9"],
    )
    reject_result = runner.invoke(
        app,
        ["org", "users", "pending", "reject", "Acme", "10"],
    )
    delete_result = runner.invoke(
        app,
        ["org", "users", "pending", "delete", "Acme", "11"],
    )

    assert approve_result.exit_code == 0
    assert reject_result.exit_code == 0
    assert delete_result.exit_code == 0
    assert pending_users.calls == [
        ("approve", "9", {}, 17),
        ("reject", "10", {}, 17),
        ("delete", "11", 17),
    ]
    assert renderer.render_calls == [
        {"id": 9, "approved": True},
        {"id": 10, "rejected": True},
        {"deleted": True, "pending_user_id": "11"},
    ]


def test_org_roles_list_passes_filters(monkeypatch):
    renderer, _, _, _, roles = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "org",
            "roles",
            "list",
            "Acme",
            "--archived",
            "false",
            "--id",
            "7",
            "--name",
            "Admin",
            "--name-contains",
            "min",
            "--name-icontains",
            "ADMIN",
            "--ordering",
            "name",
            "--page",
            "2",
            "--per-page",
            "25",
            "--search",
            "ops",
        ],
    )

    assert result.exit_code == 0
    assert roles.calls == [
        (
            "list",
            {
                "archived": False,
                "id": 7,
                "name": "Admin",
                "name__contains": "min",
                "name__icontains": "ADMIN",
                "ordering": "name",
                "page": 2,
                "per_page": 25,
                "search": "ops",
                "organisation_id": 17,
            },
        )
    ]
    assert renderer.render_list_calls == [{"results": []}]


def test_org_roles_get_renders_response(monkeypatch):
    renderer, _, _, _, roles = _fake_state(monkeypatch)

    result = runner.invoke(app, ["org", "roles", "get", "Acme", "7"])

    assert result.exit_code == 0
    assert roles.calls == [("retrieve", "7", 17)]
    assert renderer.render_calls == [{"id": 7}]
