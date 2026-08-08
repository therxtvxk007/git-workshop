"""KTU S3 CSE subject table, 2024 scheme.

Sourced from the official curriculum table (page 4 of the curriculum PDF) and
cross-checked against the detailed syllabus.

`elective_group` marks codes where only one of the group is actually taken.
`kind` distinguishes theory papers (which have university ESE question papers)
from labs (which usually have no downloadable PYQ).
"""

SUBJECTS = [
    {
        "slot": "A",
        "code": "GAMAT301",
        "name": "Mathematics for Computer and Information Science-3",
        "credits": 3,
        "kind": "theory",
    },
    {
        "slot": "B",
        "code": "PCCST302",
        "name": "Theory of Computation",
        "credits": 4,
        "kind": "theory",
    },
    {
        "slot": "C",
        "code": "PCCST303",
        "name": "Data Structures and Algorithms",
        "credits": 4,
        "kind": "theory",
    },
    {
        "slot": "D",
        "code": "PBCST304",
        "name": "Object Oriented Programming (PBL)",
        "credits": 4,
        "kind": "theory",
    },
    {
        "slot": "F",
        "code": "GAEST305",
        "name": "Digital Electronics and Logic Design",
        "credits": 4,
        "kind": "theory",
    },
    {
        "slot": "G",
        "code": "UCHUT346",
        "name": "Economics for Engineers",
        "credits": 2,
        "kind": "theory",
        "elective_group": "G",
    },
    {
        "slot": "G",
        "code": "UCHUT347",
        "name": "Engineering Ethics and Sustainable Development",
        "credits": 2,
        "kind": "theory",
        "elective_group": "G",
    },
    {
        "slot": "L",
        "code": "PCCSL307",
        "name": "Data Structures Lab",
        "credits": 2,
        "kind": "lab",
    },
    {
        "slot": "Q",
        "code": "PCCSL308",
        "name": "Digital Lab",
        "credits": 2,
        "kind": "lab",
    },
]

BY_CODE = {s["code"]: s for s in SUBJECTS}


def default_codes(include_labs=True):
    return [s["code"] for s in SUBJECTS if include_labs or s["kind"] != "lab"]
