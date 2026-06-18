-- 043_candidate_evidence_map: 候选-证据映射表 (Goal 二 Spec)
-- 对应 Spec §Goal 二 "数据模型" candidate_evidence_map 定义

CREATE TABLE IF NOT EXISTS candidate_evidence_map (
    candidate_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    PRIMARY KEY(candidate_id, evidence_id),
    FOREIGN KEY(candidate_id) REFERENCES field_candidates(candidate_id),
    FOREIGN KEY(evidence_id) REFERENCES evidence_items(evidence_id)
);
