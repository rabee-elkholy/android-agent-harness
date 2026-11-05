"""Conservative insertion points for single-line diagnostic statements."""
import re

from _vnext_common import ValidationError

TOKEN = re.compile(r'//[^\n]*|/\*|\*/|"""|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|[(){}\[\]]|[^\s]')
CONTROL = r"(?:if|while|for|catch|synchronized)\s*\(.*\)"
BLOCK = re.compile(r"(?:\bfun\s+.*\)|\b(?:if|for|while|catch)\s*\(.*\)|\b(?:else|try|finally|do|init)|->)\s*(?::\s*[\w.<>?]+)?\s*\{$")


def context(lines, stop, java):
    """Mask literals/comments and track only delimiters preceding the insertion."""
    stack = []
    comments = 0
    raw = False
    previous = ""
    multiline_header = False
    for line in lines[:stop]:
        code = []
        i = 0
        while i < len(line):
            if raw:
                end = line.find('"""', i)
                if end < 0:
                    break
                i = end + 3
                raw = False
                continue
            if comments:
                match = re.search(r"/\*|\*/", line[i:])
                if not match:
                    break
                i += match.end()
                if match.group() == "*/":
                    comments -= 1
                elif not java:
                    comments += 1
                continue
            if line[i].isspace():
                code.append(" ")
                i += 1
                continue
            match = TOKEN.match(line, i)
            token = match.group()
            i = match.end()
            if token.startswith("//"):
                break
            if token == "/*":
                comments = 1
                continue
            if token == '"""':
                raw = True
                code.append(" literal ")
                continue
            if token in {'"', "'"}:
                raise ValidationError("Ambiguous string at insertion point")
            code.append("literal" if token.startswith(('"', "'")) else token)
            if token in ("{", "(", "["):
                prefix = "".join(code).strip()
                valid = bool(BLOCK.search(prefix))
                if java and token == "{":
                    valid |= bool(re.fullmatch(r"(?:[\w<>\[\].]+\s+)+\w+\s*\([^;{}]*\)\s*\{", prefix))
                stack.append((token, valid))
            elif token in ("}", ")", "]"):
                if not stack or stack.pop()[0] != {"}": "{", ")": "(", "]": "["}[token]:
                    raise ValidationError("Unbalanced source delimiter")
        current = "".join(code).strip()
        if current:
            if re.match(r"^(?:if|for|while|when|switch|catch|synchronized)\b", current) and any(t == "(" for t, _ in stack):
                multiline_header = True
            previous = current
            if multiline_header and not any(t == "(" for t, _ in stack):
                if not current.endswith("{"):
                    previous = "if (multiline)"
                multiline_header = False
    if raw or comments or not stack or stack[-1] != ("{", True):
        raise ValidationError("Choose a statement in a recognized function or braced control body")
    return previous


def make_insertion(data, path, anchor, before, occurrence, label, values, ident):
    decoded = data.decode("utf-8-sig")
    if path.suffix == ".java" and re.search(r"\\u+[0-9a-fA-F]{4}", decoded):
        raise ValidationError("Java Unicode escapes make insertion ambiguous")
    lines = decoded.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.strip() == anchor.strip()]
    if occurrence is None and len(matches) != 1:
        raise ValidationError("Anchor must be unique or specify --occurrence")
    occurrence = 1 if occurrence is None else occurrence
    if not 1 <= occurrence <= len(matches):
        raise ValidationError("Anchor occurrence missing")
    index = matches[occurrence - 1] + (0 if before else 1)
    java = path.suffix == ".java"
    prev = context(lines, index, java)
    following = lines[index].strip() if index < len(lines) else ""
    if (not following or re.match(r'^(?:[}/).@+\-*&|?:,\[]|else\b|catch\b|finally\b|case\b|default\b|super\s*\(|this\s*\(|as\b|in\b)', following)
            or re.search(r"(?:[.,=(+\-*/&|?:]|->)\s*$", prev)
            or re.search(r"\b(?:return|throw|break|continue)\b", prev)
            or prev.startswith("@") or re.search(r"(?:\b" + CONTROL + r"|\b(?:else|do))\s*$", prev)
            or java and not prev.endswith(("{", ";", "}"))):
        raise ValidationError("Ambiguous statement boundary; choose --before another statement")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", label):
        raise ValidationError("Invalid diagnostic label")
    msg = f"#{ident} {label}"
    sets = [path.parts[i + 1] for i, part in enumerate(path.parts[:-1]) if part == "src"]
    android = java or not sets or sets[-1] in {"main", "test", "androidTest"} or sets[-1].startswith("android")
    if sets and sets[-1] not in {"main", "test", "androidTest"} and not re.search(r"(?:Main|Test)$", sets[-1]):
        android = True
    if not android:
        msg = "HarnessDbg " + msg
    expr = '"' + msg + '"'
    for value in values:
        name, sep, ref = value.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_]\w*", name) or not re.fullmatch(r"[A-Za-z_]\w*(?:(?:\.|\?\.)[A-Za-z_]\w*)*", ref):
            raise ValidationError("Values must be named variable or property references without calls")
        if java and "?." in ref:
            raise ValidationError("Safe calls require Kotlin")
        root = re.escape(re.split(r"[?.]", ref)[0])
        if re.search(r"\b(?:val|var)\s+" + root + r"\b[^\n]*(?:by\s+lazy|get\s*\()|\b(?:val|var)\s+" + root + r"\b[^\n]*\n\s*get\s*\(", "".join(lines)):
            raise ValidationError("Lazy or computed property is unsuitable for instrumentation")
        expr += ' + " ' + name + '=" + ' + ref
    indent = re.match(r"[ \t]*", lines[index]).group()
    call = f'android.util.Log.d("HarnessDbg", {expr})' if android else f'println({expr})'
    line = f"{indent}{call}{';' if java else ''} // HARNESS-DEBUG {ident}"
    end = "\r\n" if lines[index].endswith("\r\n") else "\n"
    offset = (3 if data.startswith(b"\xef\xbb\xbf") else 0) + len("".join(lines[:index]).encode())
    return data[:offset] + (line + end).encode() + data[offset:], line, end
