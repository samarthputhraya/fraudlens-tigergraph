"""Compact policy text given to the Compliance Reviewer (full text lives in the knowledge graph)."""
RULES_TEXT = """Fraud Policy v1.0 (summary of the operative rules)
Routes: auto = ALLOW_TRANSACTION, MONITOR_CARD, MONITOR_CONNECTED_CARDS, WARN_CUSTOMER, VERIFY_WITH_CUSTOMER, STEP_UP_AUTH,
GENERATE_REPORT, CREATE_CASE, ESCALATE_TO_ANALYST, CLOSE_NO_FRAUD. L1 = DECLINE_TRANSACTION; BLOCK_CARD when exposure <= $2,500.
L2 = BLOCK_CARD when exposure > $2,500; BLOCK_ALL_CARDS always; FILE_REPORT always. Only auto actions may be executed by the agent.
R1 single signal and probability < 0.70: VERIFY_WITH_CUSTOMER or STEP_UP_AUTH before any block.
R2 customer denies: BLOCK_CARD + CREATE_CASE; add FILE_REPORT if exposure > $1,000 or shared device profile / another card's fraud.
R3 customer confirms: CLOSE_NO_FRAUD. R4 no reply in 24h: MONITOR_CARD + DECLINE_TRANSACTION; escalate if exposure > $500.
R5 card testing: DECLINE_TRANSACTION + STEP_UP_AUTH; BLOCK_CARD if a purchase over $100 already cleared.
R6 shared origin across cards: name it, CREATE_CASE + FILE_REPORT + MONITOR_CONNECTED_CARDS.
R7 disputed but matches own recurring pattern: CREATE_CASE + VERIFY_WITH_CUSTOMER + WARN_CUSTOMER; do not block.
R8 uncertain and exposure > $500, or evidence conflicts: ESCALATE_TO_ANALYST.
R9 undocumented coordinated abuse: CREATE_CASE + FILE_REPORT + ESCALATE_TO_ANALYST; describe the pattern.
R10 never BLOCK_ALL_CARDS unless two cards confirmed fraud or credentials confirmed compromised.
3a: open a case at probability >= 0.30, on any evidence request or any dispute. File a SAR only when fraud is confirmed or
strongly suspected AND (exposure > $1,000 OR shared device/region cluster/another customer's fraud OR coordinated/undocumented).
6: stop at probability >= 0.85 or <= 0.15 with two independent pieces of evidence, when verification settles it, or when further
steps would not change the decision.
"""
