# STYLE_GUIDE.md

# Purpose

This document defines the coding standards for this repository.

The objective is not merely to produce working code.

The objective is to produce:

* Maintainable code
* Explainable code
* Efficient code
* Production-grade code
* Senior-engineer quality code

---

# Core Philosophy

Prefer:

1. Simplicity
2. Readability
3. Explicitness
4. Performance
5. Maintainability

Avoid unnecessary abstractions.

Avoid solving problems that do not exist.

---

# Senior Engineer Principles

## Write the Simplest Thing That Works

Prefer:

```python
df["total"] = df["price"] * df["quantity"]
```

Avoid:

```python
totals = []
for _, row in df.iterrows():
    ...
```

unless there is a clear reason.

---

## Minimize Complexity

Prefer:

* O(n)
* O(log n)

Avoid:

* O(n²)
* O(n³)

unless the dataset size makes it acceptable.

Every non-trivial algorithm should include complexity notes.

---

## Avoid Multiple Passes

Bad:

```python
for x in data:
    ...

for x in data:
    ...

for x in data:
    ...
```

Prefer:

```python
for x in data:
    ...
```

when logic can be combined safely.

---

## Minimize Memory Allocations

Avoid:

* unnecessary copies
* temporary lists
* intermediate DataFrames

Prefer:

* generators
* views
* in-place operations when safe

---

# Python Standards

## Prefer Built-ins

Prefer:

```python
sum()
any()
all()
max()
min()
zip()
enumerate()
Counter()
defaultdict()
```

Do not reinvent standard library functionality.

---

## Prefer Comprehensions

Prefer:

```python
squares = [x * x for x in nums]
```

Avoid:

```python
squares = []

for x in nums:
    squares.append(x * x)
```

unless the loop is substantially clearer.

---

## Functions

Functions should:

* have one responsibility
* be small
* be composable

Target:

* 20-40 lines
* maximum 60 lines

Large functions should be decomposed.

---

## Nesting

Avoid nesting beyond 3 levels.

Prefer:

```python
if invalid:
    return
```

instead of:

```python
if valid:
    if another:
        if another:
            ...
```

---

## Naming

Names should explain intent.

Prefer:

```python
candidate_score
resume_chunks
embedding_model
```

Avoid:

```python
x
tmp
data2
value1
```

---

# Pandas Standards

## Prefer Vectorization

Good:

```python
df["a"] = df["b"] + df["c"]
```

Bad:

```python
for row in df.iterrows():
```

---

## Avoid iterrows()

Allowed only when:

* external APIs require row-by-row processing
* logic cannot be vectorized

---

## Avoid apply()

Before using apply:

1. Consider vectorization.
2. Consider NumPy.
3. Consider groupby transforms.

---

## Avoid Repeated DataFrame Scans

Bad:

```python
df[df["x"] > 0]
df[df["y"] > 0]
df[df["z"] > 0]
```

Prefer:

single-pass operations when possible.

---

## Avoid Large DataFrame Copies

Bad:

```python
df2 = df.copy()
df3 = df2.copy()
```

---

# Refactoring Standards

Before submitting code:

1. Remove duplicate loops.
2. Remove dead code.
3. Remove unnecessary variables.
4. Remove unnecessary abstractions.
5. Remove premature optimizations.

Ask:

"Can this code be simpler?"

---

# AI Coding Requirements

The coding agent must:

1. Generate working code.
2. Review the code.
3. Refactor the code.
4. Optimize complexity.
5. Remove unnecessary loops.
6. Remove unnecessary allocations.
7. Ensure code follows this style guide.

The final answer should resemble code written by an experienced engineer rather than tutorial code.

---

# Performance Review Checklist

Before finalizing code:

* Is there an unnecessary loop?
* Is there an unnecessary copy?
* Can built-ins replace custom logic?
* Can vectorization replace iteration?
* Is memory usage reasonable?
* Is complexity acceptable?
* Is the code shorter and clearer?
* Would a senior engineer approve this implementation?

# LLM Anti-Patterns

Avoid:

- Defensive code without evidence.
- Multiple loops over the same data.
- Excessive helper functions.
- Premature abstraction.
- Reimplementing library functionality.
- Deep nesting.
- Generic exception handling:
    except Exception:
