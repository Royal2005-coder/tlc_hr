"""Anonymous surveys retain sufficient statistics, never individual ballots."""
from collections import Counter
from tlc_hr.domain.services import require


def validate_questions(questions):
    require(bool(questions), "survey_questions", "Cần ít nhất một câu hỏi")
    keys = [q["key"] for q in questions]
    require(len(keys) == len(set(keys)), "question_duplicate", "Mã câu hỏi phải duy nhất")
    for q in questions:
        options = q["options"]
        require(bool(q["label"]) and len(options) >= 2 and len(options) == len(set(options)), "question_options", "Mỗi câu cần nhãn và ít nhất hai lựa chọn khác nhau")
        require(all(isinstance(x, str) and x.strip() for x in options), "question_options", "Lựa chọn không được trống")


def ballot(questions, answers):
    validate_questions(questions)
    require(isinstance(answers, dict), "answer_shape", "Câu trả lời không hợp lệ")
    require(set(answers) == {q["key"] for q in questions if not q.get("hidden")}, "answer_questions", "Hãy trả lời đầy đủ các câu hỏi hiển thị")
    for q in questions:
        if not q.get("hidden"):
            require(answers[q["key"]] in q["options"], "answer_option", "Lựa chọn không hợp lệ")
    return answers


def aggregate_result(questions, rows, threshold):
    require(threshold >= 5, "privacy_threshold", "Ngưỡng ẩn danh tối thiểu là 5")
    counts = Counter()
    for row in rows:
        counts[(row["question"], row["option"])] += row["count"]
    # Count is per question; a partially populated group is never released.
    totals = {q["key"]: sum(counts[(q["key"], o)] for o in q["options"]) for q in questions if not q.get("hidden")}
    if not totals or min(totals.values()) < threshold:
        return {"suppressed": True}
    return {"suppressed": False, "responses": min(totals.values()), "questions": [
        {"key": q["key"], "label": q["label"], "counts": {o: counts[(q["key"], o)] for o in q["options"]}}
        for q in questions if not q.get("hidden")]}
