from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

GITHUB_API = "https://api.github.com"
USER_AGENT = "save-issues/0.1.0"


@dataclass
class IssueRef:
    owner: str
    repo: str
    number: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class IssueData:
    ref: IssueRef
    issue: dict[str, Any]
    comments: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.issue.get("title") or f"issue-{self.ref.number}"

    @property
    def state(self) -> str:
        return self.issue.get("state") or "unknown"

    @property
    def html_url(self) -> str:
        return self.issue.get("html_url") or ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.ref.owner,
            "repo": self.ref.repo,
            "number": self.ref.number,
            "issue": self.issue,
            "comments": self.comments,
            "events": self.events,
        }


class GitHubError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 30.0) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=GITHUB_API,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.status_code == 404:
            raise GitHubError(f"Not found: {path}", status_code=404)
        if response.status_code == 401:
            raise GitHubError(
                "Unauthorized. Set GITHUB_TOKEN or pass --token.",
                status_code=401,
            )
        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining == "0":
                raise GitHubError(
                    "GitHub API rate limit exceeded. Use a token or wait.",
                    status_code=403,
                )
            raise GitHubError(
                f"Forbidden: {response.text[:200]}",
                status_code=403,
            )
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub API error {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )
        return response

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        query = dict(params or {})
        query.setdefault("per_page", 100)
        page = 1
        while True:
            query["page"] = page
            response = self._request("GET", path, params=query)
            batch = response.json()
            if not isinstance(batch, list):
                raise GitHubError(f"Unexpected response for {path}")
            items.extend(batch)
            link = response.headers.get("Link", "")
            if 'rel="next"' not in link:
                break
            page += 1
        return items

    def get_issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        response = self._request("GET", f"/repos/{owner}/{repo}/issues/{number}")
        data = response.json()
        if "pull_request" in data:
            raise GitHubError(
                f"#{number} is a pull request, not an issue. Use a plain issue number."
            )
        return data

    def get_comments(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{owner}/{repo}/issues/{number}/comments")

    def get_events(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{owner}/{repo}/issues/{number}/events")

    def list_issue_numbers(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        labels: str | None = None,
        limit: int | None = None,
    ) -> list[int]:
        params: dict[str, Any] = {
            "state": state,
            "sort": "created",
            "direction": "asc",
            "per_page": 100,
        }
        if labels:
            params["labels"] = labels
        numbers: list[int] = []
        page = 1
        while True:
            params["page"] = page
            response = self._request("GET", f"/repos/{owner}/{repo}/issues", params=params)
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if "pull_request" in item:
                    continue
                numbers.append(int(item["number"]))
                if limit is not None and len(numbers) >= limit:
                    return numbers
            link = response.headers.get("Link", "")
            if 'rel="next"' not in link:
                break
            page += 1
        return numbers

    def fetch_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        include_events: bool = False,
    ) -> IssueData:
        ref = IssueRef(owner=owner, repo=repo, number=number)
        issue = self.get_issue(owner, repo, number)
        comments = self.get_comments(owner, repo, number)
        events = self.get_events(owner, repo, number) if include_events else []
        return IssueData(ref=ref, issue=issue, comments=comments, events=events)


_ISSUE_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:issues|pull)/(?P<number>\d+)",
    re.IGNORECASE,
)
_REPO_RE = re.compile(r"^(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)$")
_RANGE_RE = re.compile(r"^(?P<start>\d+)\s*-\s*(?P<end>\d+)$")


def parse_repo(value: str) -> tuple[str, str]:
    text = value.strip().rstrip("/")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ValueError(f"Invalid repo URL: {value}")
        return parts[0], parts[1]
    match = _REPO_RE.match(text)
    if not match:
        raise ValueError(f"Invalid repo: {value}. Use owner/repo")
    return match.group("owner"), match.group("repo")


def parse_issue_target(value: str) -> IssueRef | None:
    text = value.strip()
    match = _ISSUE_URL_RE.search(text)
    if match:
        return IssueRef(
            owner=match.group("owner"),
            repo=match.group("repo"),
            number=int(match.group("number")),
        )
    return None


def parse_issue_numbers(values: list[str]) -> list[int]:
    numbers: list[int] = []
    seen: set[int] = set()
    for raw in values:
        text = raw.strip()
        if not text:
            continue
        range_match = _RANGE_RE.match(text)
        if range_match:
            start = int(range_match.group("start"))
            end = int(range_match.group("end"))
            if start > end:
                start, end = end, start
            for n in range(start, end + 1):
                if n not in seen:
                    seen.add(n)
                    numbers.append(n)
            continue
        if not text.isdigit():
            raise ValueError(f"Invalid issue number: {raw}")
        n = int(text)
        if n not in seen:
            seen.add(n)
            numbers.append(n)
    return numbers
