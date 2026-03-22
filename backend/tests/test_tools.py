from tools import _merge_context_content, _normalize_document_sections


def test_merge_context_content_merges_nested_dicts():
    existing = {
        "summary": "Backend engineer",
        "location": "Remote",
        "preferences": {
            "remote": True,
            "industries": ["healthcare"],
        },
    }
    incoming = {
        "summary": "Senior backend engineer",
        "preferences": {
            "industries": ["fintech"],
            "salary": "150k+",
        },
    }

    merged = _merge_context_content(existing, incoming)

    assert merged == {
        "summary": "Senior backend engineer",
        "location": "Remote",
        "preferences": {
            "remote": True,
            "industries": ["healthcare", "fintech"],
            "salary": "150k+",
        },
    }


def test_merge_context_content_appends_unique_list_entries():
    existing = [
        {"company": "Acme", "role": "Engineer"},
        {"company": "Globex", "role": "Lead Engineer"},
    ]
    incoming = [
        {"company": "Acme", "role": "Engineer"},
        {"company": "Initech", "role": "Staff Engineer"},
    ]

    merged = _merge_context_content(existing, incoming)

    assert merged == [
        {"company": "Acme", "role": "Engineer"},
        {"company": "Globex", "role": "Lead Engineer"},
        {"company": "Initech", "role": "Staff Engineer"},
    ]


def test_normalize_document_sections_formats_resume_fields_for_template():
    normalized = _normalize_document_sections(
        "resume",
        {
            "summary": "Backend engineer",
            "skills": {
                "Languages": ["Python", "SQL"],
                "Cloud": ["GCP"],
            },
            "education": [
                {
                    "degree": "B.Sc. Computer Science",
                    "institution": "Memorial University",
                    "dates": "2021-2025",
                    "gpa": "3.8",
                }
            ],
            "experiences": [
                {
                    "company": "Acme",
                    "role": "Engineer",
                    "dates": "2022-2024",
                    "bullets": ["Built APIs", "Improved performance"],
                }
            ],
        },
    )

    assert normalized["skills"] == "Languages: Python, SQL; Cloud: GCP"
    assert normalized["education"] == "B.Sc. Computer Science, Memorial University (2021-2025 | GPA 3.8)"
    assert normalized["experiences"] == [
        {
            "company": "Acme",
            "role": "Engineer",
            "dates": "2022-2024",
            "bullets": ["Built APIs", "Improved performance"],
        }
    ]


def test_normalize_document_sections_sets_cover_letter_defaults():
    normalized = _normalize_document_sections(
        "cover_letter",
        {
            "company": "Boam AI",
            "role": "Backend Engineer",
            "paragraphs": ["Paragraph one", "Paragraph two"],
        },
    )

    assert normalized["company"] == "Boam AI"
    assert normalized["role"] == "Backend Engineer"
    assert normalized["hiring_manager"] == "Hiring Manager"
    assert normalized["paragraphs"] == ["Paragraph one", "Paragraph two"]
    assert isinstance(normalized["date"], str)
    assert normalized["date"]
