DEPARTMENTS = (
    "HR",
    "IT",
    "Finance",
    "Facilities & Maintenance",
    "General Administration",
    "Operations",
)


DEPARTMENT_TERMS = {
    "HR": [
        "annual leave", "sick leave", "maternity leave",
        "parental leave", "payslip query", "employment contract",
        "employee benefits", "workplace harassment",
        "workplace conduct", "recruitment", "probation",
        "disciplinary", "staff wellness",
    ],
    "IT": [
        "laptop", "computer", "password", "company email",
        "network", "wifi", "wi-fi", "internet",
        "software", "system access", "account locked",
        "printer", "cybersecurity", "data breach",
    ],
    "Finance": [
        "salary", "payroll", "salary deduction",
        "missing payment", "invoice", "reimbursement",
        "expense claim", "budget", "purchase order",
        "overtime payment", "tax deduction",
    ],
    "Facilities & Maintenance": [
        "air conditioner", "air conditioning",
        "office lights", "plumbing", "water leak",
        "broken door", "office cleaning", "building repair",
        "office furniture", "maintenance",
        "water dispenser", "generator",
    ],
    "General Administration": [
        "stationery", "office supplies", "document request",
        "administrative assistance", "filing",
        "meeting room booking", "company forms",
        "office records", "general enquiry",
    ],
    "Operations": [
        "operational process", "service delivery",
        "workflow", "business operations",
        "operational procedure", "process improvement",
        "daily operations", "operations support",
    ],
}


def classify_ticket(subject, description):
    """Suggest a department and priority using transparent keyword rules."""

    text = f"{subject} {description}".lower()

    scores = {
        department: sum(
            1 for term in terms if term in text
        )
        for department, terms in DEPARTMENT_TERMS.items()
    }

    highest_score = max(scores.values())

    matching_departments = [
        department
        for department, score in scores.items()
        if score == highest_score and score > 0
    ]

    requires_review = False

    if highest_score == 0:
        department = "General Administration"
        requires_review = True
        department_reason = (
            "No recognised department indicators were found. "
            "Temporarily routed to General Administration for human review."
        )
    elif len(matching_departments) > 1:
        department = "General Administration"
        requires_review = True
        department_reason = (
            "The request contains indicators for multiple departments: "
            + ", ".join(matching_departments)
            + ". Human review is required."
        )
    else:
        department = matching_departments[0]
        department_reason = (
            f"Suggested for {department} based on matching request keywords."
        )

    high_terms = [
        "unsafe", "danger", "threat", "injury",
        "harassment", "data breach", "security breach",
        "urgent", "emergency",
    ]

    medium_terms = [
        "unable", "blocked", "cannot work",
        "not working", "overdue", "missing",
        "incorrect", "complaint",
    ]

    if any(term in text for term in high_terms):
        priority = "High"
        priority_reason = (
            "Potential safety, security or urgent risk indicator."
        )
    elif any(term in text for term in medium_terms):
        priority = "Medium"
        priority_reason = (
            "Service disruption or complaint indicator."
        )
    else:
        priority = "Low"
        priority_reason = (
            "No high-risk or service-disruption indicator detected."
        )

    return {
        "department": department,
        "department_reason": department_reason,
        "requires_review": requires_review,
        "matching_departments": matching_departments,
        "priority": priority,
        "priority_reason": priority_reason,
    }
