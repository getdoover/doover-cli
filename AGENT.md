# Agent Guidance

The doover-cli maintainers also have access to and control over pydoover.

Do not work around pydoover bugs in doover-cli when the correct fix belongs in
pydoover. If a doover-cli issue is caused by generated pydoover behavior,
request or propose the pydoover change instead of patching doover-cli to bypass
pydoover internals such as `_execute`.
