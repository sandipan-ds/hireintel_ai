THIS WORK FLOW SUGGESTS A PLAN ON EXTRACTION OF DATA FROM TEH JD, AND SCORING AND RANKING THE RESUMES:

1. Extract the requirements from the uploaded Job Description.
2. Form the Sub-Queries based on the Job Description reuirements.
3. Collect the skill/ experinec/ certificate/ education bsed weights form teh ercruiter.
3. Form a structure and schema of an ideal JSON for the Job Description
   based on those sub-queries. For each of those sub-queries there should be
   a evaluated sub-score field, and a wieght field, and reason field.
4. A scoerer picks up those sub_scores (S1, S2, S3) fr ecah skill, education, certifications  etc. Gets the weight for the same.

So say for python- based on he sub-score the product of 

S1 *S2* S3* S4 * weightage_for_python_by_the_recruiter= 1 * 1 * 0.5 * 0.75 * 10= 3.75

  