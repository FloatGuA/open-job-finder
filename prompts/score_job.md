You are evaluating a job posting against a candidate.
Score EACH dimension from 0 to 100 independently. Return ONLY the JSON below, nothing else.

## Job Posting
Title: {{title}}
Company: {{company}}
JD:
{{jd_text}}

## Candidate Profile
{{profile_summary}}

## Required JSON output (fill every field, integers 0-100):
```json
{
  "dimensions": {
    "skill_match": {
      "score": <0-100>,
      "matched": ["<skill found in both JD and resume>"],
      "missing": ["<skill required by JD but absent from resume>"]
    },
    "experience_match": {
      "score": <0-100>,
      "jd_requires": "<e.g. 3-5年>",
      "candidate_has": "<from profile experience field>"
    },
    "city_match": {
      "score": <0 or 100>,
      "match": <true|false>
    },
    "salary_match": {
      "score": <0-100>,
      "offered": "<salary from JD>",
      "expected": "<from profile salary field>"
    },
    "growth_potential": {
      "score": <0-100>,
      "reason": "<1 sentence in Chinese>"
    }
  },
  "overall_reason": "<2-3 sentences in Chinese explaining the overall assessment>"
}
```

Scoring rubrics:
- skill_match 90-100: JD skills almost fully covered by resume
- skill_match 50-89: partial overlap
- skill_match 0-49: major skill gaps
- experience_match 100: exact match; 70: one level off; 0: completely mismatched (e.g. 10yr role for fresh grad)
- city_match: 100 if job city is in candidate city list, 0 otherwise
- salary_match: 100 if offered >= expected; scale down proportionally if lower; 50 if no salary info
- growth_potential: subjective — does this role advance the candidate's career direction?
