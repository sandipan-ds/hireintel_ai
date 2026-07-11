# Extraction Quality Review Queue
Generated at: 2026-07-12 00:55:28

This report compiles candidates whose resume JSON extraction failed quality audits or requires manual inspection before candidate scoring/matching.

## Overview Metrics
- **Failed / Blocked Candidates**: 1
- **Review Recommended Candidates**: 11

---

## 1. Critical (Failed / Blocked from Scoring)
These candidates scored below the threshold of `0.65` and should be skipped or re-extracted.

### 🛑 WebDesigning_CAND_0016 [WebDesigning] - Quality Score: 0.62
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.certifications`: Certification keywords like ['certified', 'oracle'] found in raw text, but certifications array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[ERROR]** `candidate_profile.experience`: Experience-related heading detected in raw text, but experience array is empty
  - *Expected*: list of entries | *Actual*: []
- **[ERROR]** `candidate_profile.education`: Education-related heading detected in raw text, but education array is empty
  - *Expected*: list of entries | *Actual*: []
- **[WARNING]** `candidate_profile.skills`: Skills-related heading detected in raw text, but skills array is empty
  - *Expected*: non-empty list | *Actual*: []

---

## 2. Warning (Review Recommended / Provisional Scoring)
These candidates scored between `0.65` and `0.84`, or triggered a critical issue. They can be scored provisionally but their data might have minor completeness anomalies.

### ⚠️ WebDesigning_CAND_0014 [WebDesigning] - Quality Score: 0.69
#### Flagged Issues:
- **[ERROR]** `candidate_profile.experience`: Experience-related heading detected in raw text, but experience array is empty
  - *Expected*: list of entries | *Actual*: []
- **[ERROR]** `candidate_profile.education`: Education-related heading detected in raw text, but education array is empty
  - *Expected*: list of entries | *Actual*: []
- **[WARNING]** `candidate_profile.skills`: Skills-related heading detected in raw text, but skills array is empty
  - *Expected*: non-empty list | *Actual*: []

### ⚠️ SalesManager_CAND_0158 [SalesManager] - Quality Score: 0.75
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[ERROR]** `candidate_profile.experience`: Experience-related heading detected in raw text, but experience array is empty
  - *Expected*: list of entries | *Actual*: []
- **[WARNING]** `candidate_profile.skills`: Skills-related heading detected in raw text, but skills array is empty
  - *Expected*: non-empty list | *Actual*: []

### ⚠️ BusinessAnalyst_CAND_0128 [BusinessAnalyst] - Quality Score: 0.79
#### Flagged Issues:
- **[ERROR]** `candidate_profile.experience`: Experience-related heading detected in raw text, but experience array is empty
  - *Expected*: list of entries | *Actual*: []
- **[ERROR]** `candidate_profile.education`: Education-related heading detected in raw text, but education array is empty
  - *Expected*: list of entries | *Actual*: []

### ⚠️ BusinessAnalyst_CAND_0132 [BusinessAnalyst] - Quality Score: 0.79
#### Flagged Issues:
- **[WARNING]** `candidate_profile.experience`: Detected 4 date ranges in raw text, but only 2 experience entries extracted
  - *Expected*: >= 2 entries | *Actual*: 2
- **[WARNING]** `candidate_profile.skills`: Skills-related heading detected in raw text, but skills array is empty
  - *Expected*: non-empty list | *Actual*: []

### ⚠️ WebDesigning_CAND_0009 [WebDesigning] - Quality Score: 0.79
#### Flagged Issues:
- **[ERROR]** `candidate_profile.education`: Education-related heading detected in raw text, but education array is empty
  - *Expected*: list of entries | *Actual*: []
- **[WARNING]** `candidate_profile.skills`: Skills-related heading detected in raw text, but skills array is empty
  - *Expected*: non-empty list | *Actual*: []

### ⚠️ SQLDeveloper_CAND_0038 [SQLDeveloper] - Quality Score: 0.82
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.certifications`: Certification keywords like ['oracle'] found in raw text, but certifications array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[ERROR]** `candidate_profile.education`: Education-related heading detected in raw text, but education array is empty
  - *Expected*: list of entries | *Actual*: []

### ⚠️ SrPythonDeveloper_CAND_0038 [SrPythonDeveloper] - Quality Score: 0.82
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.certifications`: Certification keywords like ['aws', 'oracle'] found in raw text, but certifications array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.experience`: Detected 4 date ranges in raw text, but only 2 experience entries extracted
  - *Expected*: >= 2 entries | *Actual*: 2

### ⚠️ SrPythonDeveloper_CAND_0045 [SrPythonDeveloper] - Quality Score: 0.82
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.certifications`: Certification keywords like ['aws', 'oracle'] found in raw text, but certifications array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.experience`: Detected 5 date ranges in raw text, but only 2 experience entries extracted
  - *Expected*: >= 2 entries | *Actual*: 2

### ⚠️ SrPythonDeveloper_CAND_0062 [SrPythonDeveloper] - Quality Score: 0.82
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.certifications`: Certification keywords like ['aws', 'oracle'] found in raw text, but certifications array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.experience`: Detected 4 date ranges in raw text, but only 2 experience entries extracted
  - *Expected*: >= 2 entries | *Actual*: 2

### ⚠️ WebDesigning_CAND_0003 [WebDesigning] - Quality Score: 0.82
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.certifications`: Certification keywords like ['cisco'] found in raw text, but certifications array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.experience`: Detected 5 date ranges in raw text, but only 2 experience entries extracted
  - *Expected*: >= 2 entries | *Actual*: 2

### ⚠️ SalesManager_CAND_0046 [SalesManager] - Quality Score: 0.82
#### Flagged Issues:
- **[WARNING]** `candidate_profile.phones`: Phone number pattern found in raw text but phones array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.certifications`: Certification keywords like ['azure'] found in raw text, but certifications array is empty
  - *Expected*: non-empty list | *Actual*: []
- **[WARNING]** `candidate_profile.experience`: Detected 4 date ranges in raw text, but only 2 experience entries extracted
  - *Expected*: >= 2 entries | *Actual*: 2

