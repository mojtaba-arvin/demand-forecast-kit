#!/usr/bin/env python3
"""Validate GitHub PR commit authors, committers, and co-author trailers."""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

NAME = "Mojtaba Arvin"
EMAIL = "m.arvin@live.com"
MAINTAINER = "mojtaba-arvin"
MARKER = "<!-- maintainer-directed-ai-work -->"
AUTO_LABEL = "allow-automation-commits"
AUTOMATION = {
    "github-actions[bot]": "41898282+github-actions[bot]@users.noreply.github.com",
    "dependabot[bot]": "49699333+dependabot[bot]@users.noreply.github.com",
}
WEB_FLOW = "web-flow"
WEB_FLOW_EMAIL = "noreply@github.com"
BOT_MARKERS = re.compile(
    r"(?<![a-z0-9])(?:ai[ -]?agent|agent(?:[ -]?bot)?|assistant(?:[ -]?bot)?|"
    r"copilot|claude|cursor|windsurf|codex|chatgpt|gemini|"
    r"gpt(?:[- ]?[0-9a-z.]+)?|llm|ai[ -]?model|"
    r"github[ -]?actions|dependabot|build[ -]?bot|release[ -]?bot|"
    r"automation[ -]?bot|ci[ -]?bot|bot|\\[bot\\])(?![a-z0-9])",
    re.IGNORECASE,
)
COAUTHOR = re.compile(r"^\s*co-authored-by\s*:\s*(.*?)\s*$", re.IGNORECASE)


def is_bot(name, email, login=None, account_type=None):
    if (account_type or "").lower() == "bot" or (login or "").lower().endswith("[bot]"):
        return True
    return bool(BOT_MARKERS.search(" ".join((name or "", email or "", login or ""))))


def validate(pr, commits):
    errors = []
    labels = {label.get("name", "") for label in pr.get("labels", [])}
    allow_automation = AUTO_LABEL in labels
    marker = MARKER in (pr.get("body") or "")
    maintainer_seen = False

    for item in commits:
        commit = item.get("commit") or {}
        raw_author, raw_committer = commit.get("author") or {}, commit.get("committer") or {}
        author_account, committer_account = item.get("author") or {}, item.get("committer") or {}
        sha = (item.get("sha") or "unknown")[:12]
        author = (raw_author.get("name") or "", raw_author.get("email") or "")
        committer = (raw_committer.get("name") or "", raw_committer.get("email") or "")
        author_login, committer_login = author_account.get("login"), committer_account.get("login")
        author_type, committer_type = author_account.get("type"), committer_account.get("type")

        for role, identity in (("author", author), ("committer", committer)):
            if not all(identity):
                errors.append(f"{sha}: missing {role} name/email")
        for role, identity, login in (
            ("author", author, author_login),
            ("committer", committer, committer_login),
        ):
            name, email = identity
            if login == MAINTAINER:
                if name != NAME or email.lower() != EMAIL.lower():
                    errors.append(f"{sha}: maintainer {role} must be {NAME} <{EMAIL}>")
            elif email.lower() == EMAIL.lower():
                errors.append(f"{sha}: maintainer email does not resolve to {MAINTAINER}")
        if author_login and author_type not in {"User", "Bot"}:
            errors.append(f"{sha}: unknown GitHub author account type {author_type!r}")
        if committer_login and committer_type not in {"User", "Bot"}:
            errors.append(f"{sha}: unknown GitHub committer account type {committer_type!r}")

        expected_email = AUTOMATION.get(author_login)
        automation_commit = bool(
            allow_automation
            and expected_email
            and author_type == "Bot"
            and committer_login == author_login
            and committer_type == "Bot"
            and author[0] == author_login
            and committer[0] == author_login
            and author[1].lower() == expected_email
            and committer[1].lower() == expected_email
        )
        if is_bot(*author, author_login, author_type) and not automation_commit:
            errors.append(f"{sha}: bot/agent author rejected: {author!r} login={author_login!r}")

        web_flow_committer = (
            committer_login == WEB_FLOW
            and committer[0].lower() in {"github", "web-flow"}
            and committer[1].lower() == WEB_FLOW_EMAIL
            and not is_bot(*author, author_login, author_type)
        )
        if is_bot(*committer, committer_login, committer_type) and not (
            automation_commit or web_flow_committer
        ):
            errors.append(
                f"{sha}: bot/agent committer rejected: {committer!r} login={committer_login!r}"
            )
        if committer[1].lower() == WEB_FLOW_EMAIL and not web_flow_committer:
            errors.append(f"{sha}: web-flow identity is allowed only as the linked committer")

        if author_login == MAINTAINER and author == (NAME, EMAIL):
            maintainer_seen = True
        for line in (commit.get("message") or "").splitlines():
            match = COAUTHOR.match(line)
            if match and is_bot(match.group(1), ""):
                errors.append(f"{sha}: bot/AI Co-authored-by trailer rejected: {match.group(1)!r}")

    if not commits:
        errors.append("empty PR commit list; refusing to pass")
    if marker and not maintainer_seen:
        errors.append("maintainer-directed AI work requires an exact maintainer-authored commit")
    return errors


def get_json(url, token):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "commit-identity-policy-check",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def self_test():
    def item(
        name,
        email,
        login,
        typ,
        message="feat: test",
        cname=None,
        cemail=None,
        clogin=None,
        ctype=None,
    ):
        cname = cname if cname is not None else name
        cemail = cemail if cemail is not None else email
        clogin = clogin if clogin is not None else login
        ctype = ctype if ctype is not None else typ
        return {
            "sha": "a" * 40,
            "commit": {
                "author": {"name": name, "email": email},
                "committer": {"name": cname, "email": cemail},
                "message": message,
            },
            "author": {"login": login, "type": typ} if login else None,
            "committer": {"login": clogin, "type": ctype} if clogin else None,
        }
    plain = {"body": "", "labels": []}
    def expect(pr, commits, fail):
        result = validate(pr, commits)
        assert bool(result) == fail, result

    maintainer = item(NAME, EMAIL, MAINTAINER, "User")
    human = item("External Human", "human@example.org", "external-human", "User")
    expect(plain, [maintainer], False)
    expect(plain, [human], False)
    openai_human = item("External Engineer", "engineer@openai.com", "external-engineer", "User")
    expect(plain, [openai_human], False)
    expect(plain, [item("Copilot", "bot@example.org", "copilot[bot]", "Bot")], True)
    expect(plain, [item("Build Agent", "agent@example.org", "build-agent", "User")], True)
    expect(plain, [item("Release Bot", "release@example.org", "release-bot", "User")], True)
    expect(plain, [item("GPT-4", "gpt@example.org", "model-runner", "User")], True)
    expect(
        plain,
        [
            item(
                "External",
                "human@example.org",
                "human",
                "User",
                cname="Dependabot",
                cemail="bot@example.org",
                clogin="dependabot[bot]",
                ctype="Bot",
            )
        ],
        True,
    )
    expect(plain, [item("Wrong Name", EMAIL, MAINTAINER, "User")], True)
    expect(
        plain,
        [item(NAME, EMAIL, MAINTAINER, "User", cname="Wrong Name", cemail=EMAIL)],
        True,
    )
    bot_trailer = "feat: test\\n  Co-Authored-By: Copilot <copilot[bot]@users.noreply.github.com>"
    expect(plain, [item("Human", "h@example.org", "human", "User", bot_trailer)], True)
    actions_trailer = "feat: test\nCo-authored-by: GitHub Actions <actions@example.org>"
    expect(plain, [item("Human", "h@example.org", "human", "User", actions_trailer)], True)
    expect(
        plain,
        [
            item(
                "Human",
                "h@example.org",
                "human",
                "User",
                "feat: test\\nCo-authored-by: Another Human <other@example.org>",
            )
        ],
        False,
    )
    expect({"body": MARKER, "labels": []}, [maintainer], False)
    expect({"body": MARKER, "labels": []}, [human], True)

    bot_email = AUTOMATION["github-actions[bot]"]
    forged = item("github-actions[bot]", "forged@example.org", "github-actions[bot]", "Bot")
    genuine = item("github-actions[bot]", bot_email, "github-actions[bot]", "Bot")
    expect({"body": "", "labels": [{"name": AUTO_LABEL}]}, [forged], True)
    expect({"body": "", "labels": [{"name": AUTO_LABEL}]}, [genuine], False)
    expect(plain, [genuine], True)

    webflow = item(
        "External",
        "h@example.org",
        "human",
        "User",
        cname="GitHub",
        cemail=WEB_FLOW_EMAIL,
        clogin=WEB_FLOW,
        ctype="Bot",
    )
    expect(plain, [webflow], False)
    expect(plain, [item("web-flow", WEB_FLOW_EMAIL, WEB_FLOW, "Bot")], True)
    expect(plain, [], True)
    print("PASS: commit identity policy self-tests")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--pr-number", type=int, default=int(os.getenv("PR_NUMBER", "0")))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    if not (args.repository and args.pr_number and args.token):
        if args.self_test and not args.pr_number:
            return 0
        parser.error("--repository, --pr-number and --token are required")
    base = "https://api.github.com/repos/" + args.repository
    pr = get_json(base + "/pulls/" + str(args.pr_number), args.token)
    commits, page = [], 1
    while True:
        commits_url = base + f"/pulls/{args.pr_number}/commits?per_page=100&page={page}"
        batch = get_json(commits_url, args.token)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub API returned a non-list commit response")
        commits.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    errors = validate(pr, commits)
    print(f"Checked {len(commits)} commits in {args.repository}#{args.pr_number}")
    if errors:
        print("\n".join("ERROR: " + error for error in errors))
        return 1
    print("PASS: commit authors, committers, and co-author trailers satisfy policy")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as error:
        print(f"ERROR: GitHub API HTTP {error.code}: {error.reason}", file=sys.stderr)
        sys.exit(2)
    except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as error:
        print(f"ERROR: identity validation incomplete: {error}", file=sys.stderr)
        sys.exit(2)
