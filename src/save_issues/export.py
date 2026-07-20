from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any

from markdown import markdown as md_to_html

from save_issues.github import IssueData


def slugify(text: str, fallback: str = "issue", max_len: int = 80) -> str:
    value = text.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[-\s]+", "-", value).strip("-_")
    if not value:
        value = fallback
    return value[:max_len].rstrip("-_")


def topic_name(data: IssueData) -> str:
    return slugify(data.title, fallback=f"issue-{data.ref.number}")


def _user_login(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("login") or "unknown")
    return "unknown"


def _user_avatar(user: Any) -> str | None:
    if isinstance(user, dict):
        avatar = user.get("avatar_url")
        if avatar:
            return str(avatar)
    return None


def _user_url(user: Any) -> str | None:
    if isinstance(user, dict):
        url = user.get("html_url")
        if url:
            return str(url)
    return None


def _fmt_dt(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def _labels(issue: dict[str, Any]) -> list[str]:
    labels = issue.get("labels") or []
    names: list[str] = []
    for label in labels:
        if isinstance(label, dict):
            name = label.get("name")
            if name:
                names.append(str(name))
        elif isinstance(label, str):
            names.append(label)
    return names


def _label_items(issue: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for label in issue.get("labels") or []:
        if isinstance(label, dict):
            name = label.get("name")
            if not name:
                continue
            items.append(
                {
                    "name": str(name),
                    "color": str(label.get("color") or "ededed"),
                    "description": str(label.get("description") or ""),
                }
            )
        elif isinstance(label, str):
            items.append({"name": label, "color": "ededed", "description": ""})
    return items


def _assignees(issue: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for user in issue.get("assignees") or []:
        login = _user_login(user)
        if login != "unknown":
            result.append(login)
    return result


def _contrast_text(hex_color: str) -> str:
    value = hex_color.removeprefix("#")
    if len(value) != 6:
        return "#24292f"
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
    except ValueError:
        return "#24292f"
    # relative luminance threshold
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#ffffff" if luminance < 0.55 else "#24292f"


def render_json(data: IssueData) -> str:
    return json.dumps(data.to_dict(), ensure_ascii=False, indent=2) + "\n"


def render_markdown(data: IssueData) -> str:
    issue = data.issue
    ref = data.ref
    labels = _labels(issue)
    assignees = _assignees(issue)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        "---",
        "generated-by: https://github.com/lonely-4/save-issues",
        f"generated-timestamp: {generated_at}",
        "---",
        "",
        f"# {issue.get('title') or f'Issue #{ref.number}'}",
        "",
        f"- **Repository:** `{ref.owner}/{ref.repo}`",
        f"- **Number:** #{ref.number}",
        f"- **State:** {issue.get('state', 'unknown')}",
        f"- **Author:** @{_user_login(issue.get('user'))}",
        f"- **Created:** {_fmt_dt(issue.get('created_at'))}",
        f"- **Updated:** {_fmt_dt(issue.get('updated_at'))}",
    ]
    if issue.get("closed_at"):
        lines.append(f"- **Closed:** {_fmt_dt(issue.get('closed_at'))}")
    if labels:
        lines.append(f"- **Labels:** {', '.join(f'`{x}`' for x in labels)}")
    if assignees:
        lines.append(f"- **Assignees:** {', '.join(f'@{x}' for x in assignees)}")
    if issue.get("html_url"):
        lines.append(f"- **URL:** {issue['html_url']}")
    lines.extend(["", "---", "", "## Body", ""])
    body = (issue.get("body") or "").strip()
    lines.append(body if body else "_No description provided._")
    lines.append("")

    if data.comments:
        lines.extend(["---", "", f"## Comments ({len(data.comments)})", ""])
        for idx, comment in enumerate(data.comments, start=1):
            author = _user_login(comment.get("user"))
            created = _fmt_dt(comment.get("created_at"))
            lines.append(f"### Comment {idx} — @{author} · {created}")
            lines.append("")
            cbody = (comment.get("body") or "").strip()
            lines.append(cbody if cbody else "_Empty comment._")
            lines.append("")

    if data.events:
        lines.extend(["---", "", f"## Events ({len(data.events)})", ""])
        for event in data.events:
            actor = _user_login(event.get("actor"))
            event_type = event.get("event") or "event"
            created = _fmt_dt(event.get("created_at"))
            lines.append(f"- `{created}` — **{event_type}** by @{actor}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _md_block(text: str) -> str:
    if not text.strip():
        return "<p><em>Empty.</em></p>"
    return md_to_html(
        text,
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    )


def _user_link(user: Any) -> str:
    login = html.escape(_user_login(user))
    url = _user_url(user)
    if url:
        return f'<a class="user-link" href="{html.escape(url)}">@{login}</a>'
    return f'<span class="user-link">@{login}</span>'


def _avatar_html(user: Any, size: int = 40) -> str:
    login = html.escape(_user_login(user))
    avatar = _user_avatar(user)
    if not avatar:
        return (
            f'<div class="avatar avatar-fallback" style="width:{size}px;height:{size}px"'
            f' aria-hidden="true">{login[:1].upper()}</div>'
        )
    return (
        f'<img class="avatar" src="{html.escape(avatar)}" alt="@{login}" '
        f'width="{size}" height="{size}" loading="lazy">'
    )


def _label_chips(issue: dict[str, Any]) -> str:
    chips: list[str] = []
    for item in _label_items(issue):
        bg = item["color"].removeprefix("#")
        fg = _contrast_text(bg)
        name = html.escape(item["name"])
        desc = html.escape(item["description"])
        title_attr = f' title="{desc}"' if desc else ""
        chips.append(
            f'<span class="label" style="background-color:#{html.escape(bg)};'
            f'color:{fg};border-color:#{html.escape(bg)}"{title_attr}>{name}</span>'
        )
    return " ".join(chips)


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _event_detail(event: dict[str, Any]) -> str:
    kind = str(event.get("event") or "event")
    parts: list[str] = [html.escape(kind.replace("_", " "))]
    label = event.get("label")
    if isinstance(label, dict) and label.get("name"):
        parts.append(f'<span class="event-label">{html.escape(str(label["name"]))}</span>')
    assignee = event.get("assignee")
    if isinstance(assignee, dict) and assignee.get("login"):
        parts.append(html.escape(f"@{assignee['login']}"))
    rename = event.get("rename")
    if isinstance(rename, dict):
        frm = html.escape(str(rename.get("from") or ""))
        to = html.escape(str(rename.get("to") or ""))
        if frm or to:
            parts.append(f"from <code>{frm}</code> to <code>{to}</code>")
    milestone = event.get("milestone")
    if isinstance(milestone, dict) and milestone.get("title"):
        parts.append(html.escape(str(milestone["title"])))
    commit_id = event.get("commit_id")
    if commit_id:
        sha = html.escape(str(commit_id)[:7])
        parts.append(f"<code>{sha}</code>")
    return " ".join(parts)


def _timeline_comment(
    user: Any,
    created: str,
    body_html: str,
    *,
    is_author: bool = False,
    header_extra: str = "",
) -> str:
    author_badge = ' <span class="badge">Author</span>' if is_author else ""
    extra = f" {header_extra}" if header_extra else ""
    return f"""
<div class="timeline-item">
  <div class="timeline-badge">
    {_avatar_html(user)}
  </div>
  <div class="comment">
    <div class="comment-header">
      <strong>{_user_link(user)}</strong>{author_badge}
      <span class="muted">commented on {html.escape(created)}</span>{extra}
    </div>
    <div class="markdown-body">{body_html}</div>
  </div>
</div>
""".strip()


def _timeline_event(event: dict[str, Any]) -> str:
    actor = event.get("actor")
    detail = _event_detail(event)
    created = html.escape(_fmt_dt(event.get("created_at")))
    return f"""
<div class="timeline-item timeline-event">
  <div class="timeline-badge">
    {_avatar_html(actor, size=28)}
  </div>
  <div class="event-body">
    {_user_link(actor)}
    <span class="muted">{detail} · {created}</span>
  </div>
</div>
""".strip()


def render_html(data: IssueData) -> str:
    issue = data.issue
    ref = data.ref
    title = html.escape(str(issue.get("title") or f"Issue #{ref.number}"))
    state_raw = str(issue.get("state") or "unknown")
    state = html.escape(state_raw)
    url = html.escape(str(issue.get("html_url") or ""))
    author_user = issue.get("user")
    author_login = _user_login(author_user)
    created = _fmt_dt(issue.get("created_at"))
    labels_html = _label_chips(issue)
    assignees = _assignees(issue)
    body_html = _md_block(issue.get("body") or "_No description provided._")

    state_icon = "●" if state_raw == "open" else "✓"
    state_badge = (
        f'<span class="state-badge state-{html.escape(state_raw)}">'
        f'<span class="state-icon">{state_icon}</span> {state}</span>'
    )

    sidebar_parts: list[str] = []
    if labels_html:
        sidebar_parts.append(
            f'<div class="sidebar-section"><h3>Labels</h3><div class="label-list">{labels_html}</div></div>'
        )
    if assignees:
        chips = ", ".join(f"@{html.escape(a)}" for a in assignees)
        sidebar_parts.append(
            f'<div class="sidebar-section"><h3>Assignees</h3><p>{chips}</p></div>'
        )
    sidebar_parts.append(
        f'<div class="sidebar-section"><h3>Repository</h3>'
        f'<p><code>{html.escape(ref.owner)}/{html.escape(ref.repo)}</code></p></div>'
    )
    if url:
        sidebar_parts.append(
            f'<div class="sidebar-section"><h3>Links</h3>'
            f'<p><a href="{url}">View on GitHub</a></p></div>'
        )
    sidebar_parts.append(
        '<div class="sidebar-section sidebar-generated">'
        "<h3>Generated by</h3>"
        '<p><a href="https://github.com/lonely-4/save-issues">SaveIssue</a></p>'
        "</div>"
    )
    sidebar_html = "\n".join(sidebar_parts)

    # issue body first, then comments + events ordered by time
    timeline: list[str] = [
        _timeline_comment(author_user, created, body_html, is_author=True)
    ]
    entries: list[tuple[datetime, int, str]] = []
    for idx, comment in enumerate(data.comments):
        c_user = comment.get("user")
        c_created = _fmt_dt(comment.get("created_at"))
        c_body = _md_block(comment.get("body") or "")
        is_author = _user_login(c_user) == author_login
        entries.append(
            (
                _parse_iso(comment.get("created_at")),
                idx,
                _timeline_comment(c_user, c_created, c_body, is_author=is_author),
            )
        )
    offset = len(data.comments)
    for idx, event in enumerate(data.events):
        # skip noisy cross-ref noise? keep all ops user asked for
        kind = str(event.get("event") or "")
        if kind == "mentioned":
            continue
        entries.append(
            (
                _parse_iso(event.get("created_at")),
                offset + idx,
                _timeline_event(event),
            )
        )
    entries.sort(key=lambda x: (x[0], x[1]))
    timeline.extend(html_part for _, _, html_part in entries)

    timeline_html = "\n".join(timeline)
    comment_count = len(data.comments)

    return f"""<!DOCTYPE html>
<html lang="en" data-color-mode="auto" data-light-theme="light" data-dark-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} · {html.escape(ref.owner)}/{html.escape(ref.repo)}#{ref.number}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0d1117;
      --canvas: #0d1117;
      --fg: #e6edf3;
      --muted: #8b949e;
      --border: #30363d;
      --border-muted: #21262d;
      --canvas-subtle: #161b22;
      --accent: #2f81f7;
      --accent-fg: #2f81f7;
      --open-bg: #238636;
      --open-fg: #ffffff;
      --closed-bg: #da3633;
      --closed-fg: #ffffff;
      --header-bg: #161b22;
      --comment-bg: #0d1117;
      --comment-header-bg: #161b22;
      --code-bg: #161b22;
      --blockquote-border: #3b434b;
      --shadow: 0 0 0 1px #30363d;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
      --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    }}
    @media (prefers-color-scheme: light) {{
      :root {{
        --bg: #ffffff;
        --canvas: #ffffff;
        --fg: #1f2328;
        --muted: #59636e;
        --border: #d1d9e0;
        --border-muted: #d8dee4;
        --canvas-subtle: #f6f8fa;
        --accent: #0969da;
        --accent-fg: #0969da;
        --open-bg: #1a7f37;
        --open-fg: #ffffff;
        --closed-bg: #cf222e;
        --closed-fg: #ffffff;
        --header-bg: #f6f8fa;
        --comment-bg: #ffffff;
        --comment-header-bg: #f6f8fa;
        --code-bg: #f6f8fa;
        --blockquote-border: #d1d9e0;
        --shadow: 0 0 0 1px #d1d9e0;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font: 14px/1.5 var(--font);
      background: var(--bg);
      color: var(--fg);
      -webkit-font-smoothing: antialiased;
    }}
    a {{ color: var(--accent-fg); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px 16px 64px;
    }}
    .issue-header {{
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 24px;
    }}
    .issue-title {{
      margin: 0 0 8px;
      font-size: 32px;
      font-weight: 400;
      line-height: 1.25;
      word-wrap: break-word;
    }}
    .issue-title .number {{
      color: var(--muted);
      font-weight: 300;
    }}
    .issue-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    .state-badge {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 0 12px;
      height: 32px;
      border-radius: 2em;
      font-size: 14px;
      font-weight: 500;
      line-height: 32px;
      text-transform: capitalize;
    }}
    .state-open {{ background: var(--open-bg); color: var(--open-fg); }}
    .state-closed {{ background: var(--closed-bg); color: var(--closed-fg); }}
    .state-icon {{ font-size: 12px; }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 296px;
      gap: 24px;
      align-items: start;
    }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: minmax(0, 1fr); }}
      .sidebar {{ order: -1; }}
    }}
    .timeline {{
      position: relative;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 0;
      padding-left: 0;
    }}
    .timeline::before {{
      content: "";
      position: absolute;
      top: 20px;
      bottom: 20px;
      left: 19px;
      width: 2px;
      background: var(--border);
      z-index: 0;
    }}
    .timeline-item {{
      position: relative;
      display: grid;
      grid-template-columns: 40px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      padding: 8px 0 16px;
      z-index: 1;
    }}
    .timeline-item:last-child {{ padding-bottom: 0; }}
    .timeline-badge {{
      position: relative;
      z-index: 2;
      display: flex;
      justify-content: center;
      width: 40px;
      background: var(--bg);
      padding: 0;
    }}
    .avatar {{
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: var(--canvas-subtle);
      border: 2px solid var(--bg);
      box-shadow: 0 0 0 1px var(--border);
      object-fit: cover;
      flex-shrink: 0;
    }}
    .avatar-fallback {{
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
      color: var(--muted);
      font-size: 14px;
    }}
    .comment {{
      min-width: 0;
      background: var(--comment-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      box-shadow: var(--shadow);
    }}
    .comment-header {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      background: var(--comment-header-bg);
      border-bottom: 1px solid var(--border);
      border-radius: 6px 6px 0 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .comment-header strong {{ color: var(--fg); font-weight: 600; }}
    .user-link {{ font-weight: 600; color: var(--fg); }}
    .user-link:hover {{ color: var(--accent-fg); }}
    .badge {{
      display: inline-block;
      padding: 0 7px;
      font-size: 12px;
      font-weight: 500;
      line-height: 18px;
      border: 1px solid var(--border);
      border-radius: 2em;
      color: var(--muted);
    }}
    .muted {{ color: var(--muted); }}
    .markdown-body {{
      min-width: 0;
      padding: 16px;
      font-size: 14px;
      line-height: 1.5;
      word-wrap: break-word;
      overflow-wrap: anywhere;
    }}
    .markdown-body > :first-child {{ margin-top: 0; }}
    .markdown-body > :last-child {{ margin-bottom: 0; }}
    .markdown-body p,
    .markdown-body blockquote,
    .markdown-body ul,
    .markdown-body ol,
    .markdown-body dl,
    .markdown-body table,
    .markdown-body pre,
    .markdown-body details {{
      margin-top: 0;
      margin-bottom: 16px;
    }}
    .markdown-body h1,
    .markdown-body h2,
    .markdown-body h3,
    .markdown-body h4,
    .markdown-body h5,
    .markdown-body h6 {{
      margin-top: 24px;
      margin-bottom: 16px;
      font-weight: 600;
      line-height: 1.25;
    }}
    .markdown-body h1 {{ font-size: 2em; border-bottom: 1px solid var(--border-muted); padding-bottom: 0.3em; }}
    .markdown-body h2 {{ font-size: 1.5em; border-bottom: 1px solid var(--border-muted); padding-bottom: 0.3em; }}
    .markdown-body h3 {{ font-size: 1.25em; }}
    .markdown-body ul,
    .markdown-body ol {{ padding-left: 2em; }}
    .markdown-body blockquote {{
      padding: 0 1em;
      color: var(--muted);
      border-left: 0.25em solid var(--blockquote-border);
    }}
    .markdown-body code {{
      font-family: var(--mono);
      font-size: 85%;
      padding: 0.2em 0.4em;
      margin: 0;
      background: var(--code-bg);
      border-radius: 6px;
    }}
    .markdown-body pre {{
      padding: 16px;
      overflow: auto;
      font-size: 85%;
      line-height: 1.45;
      background: var(--code-bg);
      border-radius: 6px;
      border: 1px solid var(--border);
    }}
    .markdown-body pre code {{
      padding: 0;
      margin: 0;
      background: transparent;
      border: 0;
      font-size: 100%;
      word-break: normal;
      white-space: pre;
    }}
    .markdown-body table {{
      display: block;
      width: max-content;
      max-width: 100%;
      overflow: auto;
      border-spacing: 0;
      border-collapse: collapse;
    }}
    .markdown-body table th,
    .markdown-body table td {{
      padding: 6px 13px;
      border: 1px solid var(--border);
    }}
    .markdown-body table tr {{
      background: var(--comment-bg);
      border-top: 1px solid var(--border-muted);
    }}
    .markdown-body table tr:nth-child(2n) {{ background: var(--canvas-subtle); }}
    .markdown-body img {{
      max-width: 100%;
      height: auto;
      box-sizing: content-box;
      background: transparent;
      border-style: none;
      border-radius: 6px;
    }}
    .markdown-body video,
    .markdown-body iframe {{
      max-width: 100%;
    }}
    .timeline-event {{
      align-items: center;
      padding: 4px 0 8px;
    }}
    .timeline-event .avatar {{
      width: 28px;
      height: 28px;
    }}
    .event-body {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 14px;
      min-height: 28px;
      padding: 2px 0;
    }}
    .event-label {{
      display: inline-block;
      padding: 0 7px;
      border: 1px solid var(--border);
      border-radius: 2em;
      font-size: 12px;
      line-height: 18px;
      color: var(--fg);
      background: var(--canvas-subtle);
    }}
    .sidebar {{
      min-width: 0;
      font-size: 12px;
    }}
    .sidebar-section {{
      padding: 16px 0;
      border-bottom: 1px solid var(--border);
    }}
    .sidebar-section:first-child {{ padding-top: 0; }}
    .sidebar-section:last-child,
    .sidebar-generated {{
      border-bottom: none;
    }}
    .sidebar-section h3 {{
      margin: 0 0 8px;
      font-size: 12px;
      font-weight: 600;
      color: var(--fg);
    }}
    .sidebar-section p {{ margin: 0; color: var(--muted); word-break: break-word; }}
    .label-list {{ display: flex; flex-wrap: wrap; gap: 4px; }}
    .label {{
      display: inline-block;
      padding: 0 10px;
      font-size: 12px;
      font-weight: 500;
      line-height: 22px;
      border: 1px solid transparent;
      border-radius: 2em;
      white-space: nowrap;
    }}
    .comments-count {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 14px;
    }}
    code {{ font-family: var(--mono); font-size: 85%; }}
  </style>
</head>
<body>
  <div class="page">
    <header class="issue-header">
      <h1 class="issue-title">{title} <span class="number">#{ref.number}</span></h1>
      <div class="issue-meta">
        {state_badge}
        <span>{_user_link(author_user)} opened this issue on {html.escape(created)}
        · {comment_count} comment{"s" if comment_count != 1 else ""}</span>
      </div>
    </header>
    <div class="layout">
      <main class="timeline">
        {timeline_html}
      </main>
      <aside class="sidebar">
        {sidebar_html}
      </aside>
    </div>
  </div>
</body>
</html>
"""


def build_files(data: IssueData, topic: str | None = None) -> dict[str, str]:
    name = topic or topic_name(data)
    return {
        f"{name}.json": render_json(data),
        f"{name}.md": render_markdown(data),
        f"{name}.html": render_html(data),
    }
