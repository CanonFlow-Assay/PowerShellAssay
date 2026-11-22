"""Run the reviewed PowerShell AST adapter without loading target scripts."""

import re


def inspect(target):
    source = target.contents.decode("utf-8")
    # ParseInput can resolve dependencies while parsing some directives.
    # Reject those lexical candidates before handing any bytes to the parser.
    # Removing continuations and backticks makes the guard conservative.
    lexical = re.sub(r"\x60(?:\r?\n)?", "", source)
    directive = re.search(r"(?i)\b(?:using|configuration)\b|#\s*requires\b", lexical)
    if directive:
        target.finding("PS002", lexical.count("\n", 0, directive.start()) + 1)
        return

    result = target.call(
        "pwsh", ["-NoLogo", "-NoProfile", "-NonInteractive", "-File", "./inspect.ps1"], (0,),
    )
    if result is None:
        return

    from .engine import strict_json

    try:
        findings = strict_json(result.stdout)
        if not isinstance(findings, list):
            raise ValueError("expected AST diagnostic array")
        for finding in findings:
            rule, line, column, native_id = (finding[key] for key in ("id", "line", "column", "nativeId"))
            if rule not in {"PS001", "PS003", "PS004", "PS005", "PS006"} or not all(
                type(value) is int and value > 0 for value in (line, column)
            ):
                raise ValueError("invalid AST diagnostic")
            if native_id is not None and (
                not isinstance(native_id, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,120}", native_id)
            ):
                raise ValueError("invalid native diagnostic identity")
            target.finding(rule, line, column, native_id)
    except (KeyError, TypeError, ValueError, RecursionError):
        target.failures.append("pwsh: malformed AST adapter output")
