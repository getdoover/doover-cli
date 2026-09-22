from doover_cli.tunnel_exec import fast_args


def test_ssh_and_tunnel_with_a_device_go_to_the_binary():
    assert fast_args(["ssh", "dev", "--", "-l", "root", "uptime"]) == [
        "ssh",
        "dev",
        "--",
        "-l",
        "root",
        "uptime",
    ]
    assert fast_args(["tunnel", "dev", "SSH", "-p", "2222"]) == [
        "open",
        "dev",
        "SSH",
        "-p",
        "2222",
    ]
    assert fast_args(["ssh", "--help"]) == ["ssh", "--help"]


def test_bare_verbs_and_other_commands_stay_in_python():
    assert fast_args(["ssh"]) is None
    assert fast_args(["tunnel"]) is None
    assert fast_args(["device", "list"]) is None
    assert fast_args(["--debug", "ssh", "dev"]) is None
    assert fast_args([]) is None
