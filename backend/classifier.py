DEPARTMENTS = ("HR", "IT", "Finance", "Operations")


def classify_ticket(subject, description):
    """
    Transparent baseline classifier.
    These are suggestions, not final decisions.
    A staff member can change the department or priority.
    """
    text = f"{subject} {description}".lower()

    department_terms = {
        "HR": ["leave", "salary", "harassment", "manager", "workplace",
               "payslip", "recruitment", "benefit", "disciplinary"],
        "IT": ["laptop", "computer", "email", "password", "network",
               "software", "system", "printer", "internet", "access"],
        "Finance": ["invoice", "payment", "reimbursement", "expense",
                    "budget", "purchase order", "claim"],
        "Operations": ["building", "office", "cleaning", "security",
                       "equipment", "maintenance", "facility"]
    }

    scores = {
        department: sum(1 for word in terms if word in text)
        for department, terms in department_terms.items()
    }

    best_department = max(scores, key=scores.get)
    if scores[best_department] == 0:
        best_department = "Operations"
        department_reason = "No strong department indicators; routed to Operations for review."
    else:
        department_reason = (
            f"Suggested from matching terms for {best_department}."
        )

    high_terms = [
        "unsafe", "danger", "threat", "injury", "harassment",
        "data breach", "security breach", "urgent", "emergency"
    ]
    medium_terms = [
        "unable", "blocked", "cannot work", "not working",
        "overdue", "missing", "incorrect", "complaint"
    ]

    if any(term in text for term in high_terms):
        priority = "High"
        priority_reason = "Potential safety, security or urgent risk indicator."
    elif any(term in text for term in medium_terms):
        priority = "Medium"
        priority_reason = "Service disruption or complaint indicator."
    else:
        priority = "Low"
        priority_reason = "No high-risk or service-disruption indicator detected."

    return {
        "department": best_department,
        "department_reason": department_reason,
        "priority": priority,
        "priority_reason": priority_reason
    }
