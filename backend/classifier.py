import re


DEPARTMENTS = (
    "HR",
    "IT",
    "Finance",
    "Facilities & Maintenance",
    "General Administration",
    "Operations",
)


# Each phrase has a weight.
# More specific phrases receive higher weights.

DEPARTMENT_TERMS = {
    "HR": {
        "sexual assault": 20,
        "sexual harassment": 20,
        "workplace harassment": 15,
        "sexual abuse": 20,
        "rape": 20,
        "assault": 15,
        "workplace violence": 15,
        "bullying": 10,
        "discrimination": 10,
        "unfair treatment": 10,
        "annual leave": 8,
        "sick leave": 8,
        "maternity leave": 8,
        "parental leave": 8,
        "payslip query": 8,
        "employment contract": 8,
        "employee benefits": 8,
        "workplace conduct": 8,
        "recruitment": 8,
        "probation": 8,
        "disciplinary": 8,
        "staff wellness": 8,
        "employee grievance": 10,
        "resignation": 8,
        "unfair dismissal": 12,
    },

    "IT": {
        "cybersecurity": 12,
        "data breach": 15,
        "security breach": 15,
        "computer": 8,
        "laptop": 8,
        "password": 8,
        "company email": 8,
        "network": 8,
        "wifi": 8,
        "wi-fi": 8,
        "internet": 8,
        "software": 8,
        "system access": 8,
        "account locked": 8,
        "printer is not working": 12,
        "printer not working": 12,
        "printer error": 12,
        "printer jam": 12,
        "printer offline": 12,
        "printer is broken": 12,
        "printer broken": 12,
        "printer is faulty": 12,
        "server": 10,
        "application error": 10,
        "computer virus": 12,
        "system down": 12,
        "technical support": 8,
    },

    "Finance": {
        "not getting paid": 20,
        "not been paid": 20,
        "not paid": 18,
        "unpaid salary": 20,
        "salary not received": 20,
        "wages not paid": 20,
        "missing salary": 20,
        "pay not received": 20,
        "salary delayed": 18,
        "late salary": 18,
        "missing payment": 15,
        "salary deduction": 12,
        "salary": 10,
        "wages": 10,
        "payroll": 10,
        "overtime payment": 12,
        "overtime": 8,
        "invoice": 8,
        "reimbursement": 10,
        "expense claim": 10,
        "budget": 8,
        "purchase order": 8,
        "tax deduction": 8,
        "payment": 8,
        "supplier payment": 10,
    },

    "Facilities & Maintenance": {
        "spilled on my desk": 18,
        "spilled on the desk": 18,
        "drink on my desk": 18,
        "liquid on my desk": 18,
        "cold drink": 12,
        "coldrink": 12,
        "colddrink": 12,
        "spilled drink": 15,
        "drink spill": 15,
        "water spill": 15,
        "liquid spill": 15,
        "spilled": 10,
        "spill": 10,
        "poured on": 10,
        "desk is wet": 12,
        "wet floor": 12,
        "office lights": 8,
        "air conditioner": 8,
        "air conditioning": 8,
        "plumbing": 10,
        "water leak": 12,
        "leaking pipe": 12,
        "broken door": 8,
        "office cleaning": 8,
        "building repair": 10,
        "office furniture": 8,
        "maintenance": 10,
        "water dispenser": 8,
        "generator": 8,
        "broken chair": 10,
        "broken desk": 10,
        "electrical fault": 12,
        "power outage": 10,
        "blocked toilet": 12,
        "toilet": 8,
        "leaking tap": 10,
        "broken window": 10,
        "office carpet": 8,
        "aircon": 8,
        "cleaning": 8,
        "pest control": 10,
    },

    "General Administration": {
        "printer paper": 10,
        "stationery": 8,
        "office supplies": 8,
        "document request": 8,
        "administrative assistance": 8,
        "filing": 8,
        "meeting room booking": 8,
        "meeting room": 8,
        "book a meeting room": 10,
        "meeting space": 8,
        "company forms": 8,
        "office records": 8,
        "general enquiry": 8,
        "reception": 8,
        "visitor access": 8,
        "courier": 8,
        "office booking": 8,
    },

    "Operations": {
        "operational process": 10,
        "service delivery": 10,
        "workflow": 8,
        "business operations": 10,
        "operational procedure": 10,
        "process improvement": 10,
        "daily operations": 8,
        "operations support": 8,
        "stock management": 8,
        "inventory management": 8,
        "production delay": 10,
        "service disruption": 10,
    },
}


HIGH_PRIORITY_TERMS = [
    "sexual assault",
    "sexual harassment",
    "sexual abuse",
    "rape",
    "assault",
    "workplace violence",
    "harassment",
    "bullying",
    "discrimination",
    "threat",
    "injury",
    "unsafe",
    "danger",
    "emergency",
    "data breach",
    "security breach",
    "not getting paid",
    "not been paid",
    "not paid",
    "unpaid salary",
    "salary not received",
    "wages not paid",
    "missing salary",
    "pay not received",
    "salary delayed",
    "late salary",
    "electrical hazard",
    "electric shock",
    "fire",
    "gas leak",
    "serious leak",
]


MEDIUM_PRIORITY_TERMS = [
    "unable",
    "blocked",
    "cannot work",
    "cannot connect",
    "connection issue",
    "wifi not working",
    "can't work",
    "not working",
    "overdue",
    "missing",
    "incorrect",
    "complaint",
    "spilled",
    "spill",
    "coldrink",
    "colddrink",
    "cold drink",
    "water leak",
    "broken",
    "damaged",
    "faulty",
    "not functioning",
    "repair",
    "cleaning",
    "salary query",
    "payment query",
    "delayed",
]


SENSITIVE_TERMS = [
    "sexual assault",
    "sexual harassment",
    "sexual abuse",
    "rape",
    "workplace violence",
    "harassment",
    "bullying",
    "discrimination",
    "assault",
]


def normalise_text(subject, description):
    text = "{} {}".format(subject or "", description or "")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def classify_ticket(subject, description):
    """
    Transparent keyword-based department and priority classifier.
    This is a rules-based baseline, not a trained machine-learning model.
    """

    text = normalise_text(subject, description)

    scores = {}
    matched_terms = {}

    for department, terms in DEPARTMENT_TERMS.items():
        scores[department] = 0
        matched_terms[department] = []

        for term, weight in terms.items():
            if term in text:
                scores[department] += weight
                matched_terms[department].append(term)

    highest_score = max(scores.values())

    matching_departments = [
        department
        for department, score in scores.items()
        if score > 0
    ]

    requires_review = False

    if highest_score == 0:
        department = "General Administration"
        requires_review = True

        department_reason = (
            "No recognised department indicators were found. "
            "Temporarily routed to General Administration for human review."
        )

    else:
        best_departments = [
            department
            for department, score in scores.items()
            if score == highest_score
        ]

        if len(best_departments) > 1:
            department = "General Administration"
            requires_review = True

            department_reason = (
                "Multiple departments received the same classification "
                "score. Human review is required. Possible departments: "
                + ", ".join(best_departments)
            )

        else:
            department = best_departments[0]

            department_reason = (
                "Suggested for {} based on recognised indicators: {}."
            ).format(
                department,
                ", ".join(matched_terms[department])
            )

            # A secondary department match means the routing
            # should be checked by a human.
            if len(matching_departments) > 1:
                requires_review = True
                department_reason += (
                    " Other department indicators were also detected."
                )

    high_matches = [
        term for term in HIGH_PRIORITY_TERMS
        if term in text
    ]

    medium_matches = [
        term for term in MEDIUM_PRIORITY_TERMS
        if term in text
    ]

    sensitive_matches = [
        term for term in SENSITIVE_TERMS
        if term in text
    ]

    if high_matches:
        priority = "High"
        priority_reason = (
            "High-risk or serious financial indicator detected: "
            + ", ".join(high_matches)
        )

    elif medium_matches:
        priority = "Medium"
        priority_reason = (
            "Service disruption, maintenance or complaint indicator: "
            + ", ".join(medium_matches)
        )

    else:
        priority = "Low"
        priority_reason = (
            "No recognised high-risk or medium-priority indicator detected."
        )

    # Sensitive workplace incidents must always receive human review.
    if sensitive_matches:
        requires_review = True

    salary_risk_terms = [
        "not getting paid",
        "not been paid",
        "not paid",
        "unpaid salary",
        "salary not received",
        "wages not paid",
        "missing salary",
        "pay not received",
        "salary delayed",
        "late salary",
    ]

    if any(term in text for term in salary_risk_terms):
        requires_review = True

    return {
        "department": department,
        "department_reason": department_reason,
        "requires_review": requires_review,
        "matching_departments": matching_departments,
        "priority": priority,
        "priority_reason": priority_reason,
    }
