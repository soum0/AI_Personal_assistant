"""
Fetch GitHub repos via PyGithub and produce 4 chunk types per repo:
  overview, tech_stack, architecture, tradeoffs.

Repo URLs are read from config.yaml by ingest.py and passed in here.
"""
import itertools
import re

from github import Github, GithubException
from langchain_text_splitters import RecursiveCharacterTextSplitter

_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

_ARCH_KEYWORDS = frozenset(
    {"architecture", "structure", "design", "how it works", "overview",
     "system", "flow", "pipeline", "components", "diagram"}
)
_TRADEOFF_KEYWORDS = frozenset(
    {"tradeoff", "trade-off", "decision", "why", "chose", "instead",
     "alternative", "limitation", "known issue", "todo", "future",
     "improvement", "caveat", "shortcoming", "what i'd"}
)
_TECH_KEYWORDS = frozenset(
    {"tech", "stack", "install", "require", "depend", "setup",
     "tool", "framework", "librar", "prerequisit"}
)

# Files that reveal tech stack
_DEP_FILES = (
    "requirements.txt", "pyproject.toml", "package.json",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
)


def load_github_repos(
    repo_urls: list[str],
    token: str = "",
    max_commits: int = 30,
) -> list[dict]:
    g = Github(token) if token else Github()
    chunks: list[dict] = []
    for url in repo_urls:
        name = _parse_repo_name(url)
        if not name:
            print(f"  Skipping unrecognised URL: {url}")
            continue
        print(f"  Fetching {name}...")
        try:
            repo = g.get_repo(name)
            chunks.extend(_repo_to_chunks(repo, max_commits))
        except GithubException as exc:
            print(f"  Failed to fetch {name}: {exc}")
    return chunks


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_repo_name(url: str) -> str | None:
    m = re.search(r"github\.com[/:]([^/]+/[^/\s]+?)(?:\.git)?$", url.rstrip("/"))
    return m.group(1) if m else None


def _repo_to_chunks(repo, max_commits: int) -> list[dict]:
    readme     = _get_readme(repo)
    md_sections = _parse_md_sections(readme)
    file_tree  = _get_file_tree(repo)
    commits    = _get_commit_messages(repo, max_commits)
    issues     = _get_open_issues(repo)
    languages  = _get_languages(repo)
    dep_text   = _get_dep_file(repo)

    base = {"source": "github", "repo_name": repo.full_name}
    out  = []

    for chunk_type, text_fn in (
        ("overview",    lambda: _build_overview(repo, md_sections, readme)),
        ("tech_stack",  lambda: _build_tech_stack(repo, languages, dep_text, md_sections)),
        ("architecture", lambda: _build_architecture(file_tree, md_sections)),
        ("tradeoffs",   lambda: _build_tradeoffs(md_sections, commits, issues)),
    ):
        text = text_fn()
        meta = {**base, "type": chunk_type, "section": chunk_type}
        out.extend(_make_chunks(text, meta))

    return out


def _make_chunks(text: str, metadata: dict) -> list[dict]:
    if not text.strip():
        return []
    parts = _SPLITTER.split_text(text) if len(text) > 1000 else [text]
    return [{"text": p.strip(), "metadata": metadata} for p in parts if p.strip()]


def _get_readme(repo) -> str:
    try:
        return repo.get_readme().decoded_content.decode("utf-8", errors="ignore")
    except GithubException:
        return ""


def _parse_md_sections(markdown: str) -> dict[str, str]:
    """Split markdown by ATX headers → {lowercased header: body}."""
    sections: dict[str, list[str]] = {"intro": []}
    current = "intro"
    for line in markdown.splitlines():
        if line.startswith("#"):
            if sections[current]:
                pass  # keep accumulating
            current = line.lstrip("#").strip().lower()
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _get_file_tree(repo) -> list[str]:
    try:
        return [c.name for c in repo.get_contents("")]
    except GithubException:
        return []


def _get_commit_messages(repo, n: int) -> list[str]:
    try:
        msgs = []
        for commit in itertools.islice(repo.get_commits(), n):
            first_line = commit.commit.message.splitlines()[0]
            msgs.append(first_line)
        return msgs
    except GithubException:
        return []


def _get_open_issues(repo) -> list[str]:
    try:
        return [i.title for i in itertools.islice(repo.get_issues(state="open"), 20)]
    except GithubException:
        return []


def _get_languages(repo) -> dict[str, int]:
    try:
        return repo.get_languages()
    except GithubException:
        return {}


def _get_dep_file(repo) -> str:
    for name in _DEP_FILES:
        try:
            content = repo.get_contents(name).decoded_content.decode("utf-8", errors="ignore")
            return f"# {name}\n{content[:1500]}"
        except GithubException:
            continue
    return ""


# ── chunk builders ────────────────────────────────────────────────────────────

def _build_overview(repo, sections: dict[str, str], readme: str) -> str:
    parts = [
        f"Repository: {repo.full_name}",
        f"Description: {repo.description or 'N/A'}",
        f"Stars: {repo.stargazers_count}  Forks: {repo.forks_count}  Primary language: {repo.language or 'N/A'}",
    ]
    if repo.topics:
        parts.append(f"Topics: {', '.join(repo.topics)}")
    intro = sections.get("intro") or readme[:1200]
    parts.append("\n--- README intro ---\n" + intro[:1200])
    return "\n".join(parts)


def _build_tech_stack(repo, languages: dict[str, int], dep_text: str, sections: dict[str, str]) -> str:
    parts = [f"Tech stack for {repo.full_name}:"]
    if languages:
        total = sum(languages.values()) or 1
        breakdown = ", ".join(
            f"{lang} {bytes_ * 100 // total}%"
            for lang, bytes_ in sorted(languages.items(), key=lambda x: -x[1])
        )
        parts.append(f"Language breakdown: {breakdown}")
    if dep_text:
        parts.append(dep_text)
    for header, body in sections.items():
        if any(kw in header for kw in _TECH_KEYWORDS):
            parts.append(f"\n## {header.title()}\n{body[:800]}")
    return "\n".join(parts)


def _build_architecture(file_tree: list[str], sections: dict[str, str]) -> str:
    parts: list[str] = []
    if file_tree:
        tree_lines = "\n".join(f"  {f}" for f in sorted(file_tree))
        parts.append(f"Top-level file structure:\n{tree_lines}")
    for header, body in sections.items():
        if any(kw in header for kw in _ARCH_KEYWORDS):
            parts.append(f"\n## {header.title()}\n{body[:1000]}")
    return "\n".join(parts) if parts else "No architecture information available."


def _build_tradeoffs(sections: dict[str, str], commits: list[str], issues: list[str]) -> str:
    parts: list[str] = []
    for header, body in sections.items():
        if any(kw in header for kw in _TRADEOFF_KEYWORDS):
            parts.append(f"\n## {header.title()}\n{body[:1000]}")
    if commits:
        bullet = "\n".join(f"  - {m}" for m in commits)
        parts.append(f"\nRecent {len(commits)} commit messages:\n{bullet}")
    if issues:
        bullet = "\n".join(f"  - {i}" for i in issues)
        parts.append(f"\nOpen issues ({len(issues)}):\n{bullet}")
    return "\n".join(parts) if parts else "No tradeoff information available."
