"""
Parse a PDF resume and split into named sections.
PyPDF2 for extraction, LangChain RecursiveCharacterTextSplitter for
sub-chunking sections that exceed 800 chars.
"""
import re
from pathlib import Path

import PyPDF2
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Maps lowercased keyword → canonical section name (and chunk type)
_SECTION_MAP: dict[str, str] = {
    "education": "Education",
    "academic background": "Education",
    "academic": "Education",
    "experience": "Experience",
    "work experience": "Experience",
    "professional experience": "Experience",
    "employment": "Experience",
    "internship": "Experience",
    "internships": "Experience",
    "projects": "Projects",
    "personal projects": "Projects",
    "academic projects": "Projects",
    "side projects": "Projects",
    "skills": "Skills",
    "technical skills": "Skills",
    "core skills": "Skills",
    "competencies": "Skills",
    "technologies": "Skills",
    "tools & technologies": "Skills",
    "summary": "Summary",
    "objective": "Summary",
    "profile": "Summary",
    "about me": "Summary",
    "certifications": "Certifications",
    "certificates": "Certifications",
    "awards": "Certifications",
    "achievements": "Certifications",
    "publications": "Publications",
    "research": "Publications",
}

_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=80)


def _extract_text(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        return "\n".join(page.extract_text() or "" for page in reader.pages)


def _detect_section(line: str) -> str | None:
    """Return canonical section name if line looks like a section header, else None."""
    stripped = line.strip()
    # Headers are short and not pure whitespace
    if not stripped or len(stripped) > 60:
        return None

    lower = stripped.lower().rstrip(":").strip()

    # Exact map lookup
    if lower in _SECTION_MAP:
        return _SECTION_MAP[lower]

    # Partial map lookup (keyword is substring of header)
    for keyword, canonical in _SECTION_MAP.items():
        if keyword in lower and len(lower) <= len(keyword) + 12:
            return canonical

    # Heuristic: ALL-CAPS short line without a year (e.g. "EXPERIENCE" not "JUNE 2023")
    if stripped.isupper() and 3 < len(stripped) < 40 and not re.search(r"\d{4}", stripped):
        return stripped.title()

    return None


def _section_type(section_name: str) -> str:
    lower = section_name.lower()
    for keyword, canonical in _SECTION_MAP.items():
        if keyword in lower:
            return canonical.lower().replace(" ", "_")
    return "other"


def load_resume(pdf_path: str) -> list[dict]:
    """
    Parse resume PDF into section-level chunks.

    Returns list of:
        {"text": str, "metadata": {"source", "type", "repo_name", "section"}}
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found at: {pdf_path}")

    raw = _extract_text(pdf_path)

    # Split raw text into labelled sections
    sections: dict[str, list[str]] = {"Header": []}
    current = "Header"

    for line in raw.splitlines():
        detected = _detect_section(line)
        if detected:
            current = detected
            sections.setdefault(current, [])
        else:
            sections[current].append(line)

    chunks = []
    for section_name, lines in sections.items():
        text = "\n".join(lines).strip()
        if len(text) < 30:
            continue  # skip empty or near-empty sections

        section_type = _section_type(section_name)

        # Sub-chunk large sections so each chunk fits in the context window comfortably
        sub_texts = _SPLITTER.split_text(text) if len(text) > 800 else [text]

        for sub in sub_texts:
            sub = sub.strip()
            if sub:
                chunks.append({
                    "text": sub,
                    "metadata": {
                        "source": "resume",
                        "type": section_type,
                        "repo_name": "",
                        "section": section_name,
                    },
                })

    return chunks
