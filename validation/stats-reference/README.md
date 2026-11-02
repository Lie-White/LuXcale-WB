# Fixed P5 statistics references

Read-only source: `C:\dev\prism\validation\r\reference.json` and
`anova_reference.json`, copied without changing numeric values. Generator sources
`make_reference.R`, `make_anova_reference.R`, and `studentized_range_integrate.R`
were read in the source project. Both JSON files report R 4.4.3 (ucrt).
The two source JSONs retain their original CRLF and trailing blank line; Git
attributes disable newline conversion so their audited byte hashes are preserved.

- Descriptive cases: all 11, including n=1, n=2, 1e9 offset, tiny scale, and
  90%/95%/99% confidence levels.
- t-test cases: all 19 Student/Welch cases, including Student n=1 in one group.
  The three paired and two one-sample cases are outside this unpaired-v1 scope.
- ANOVA/Tukey: all 11 cases, including both confidence levels for unequal groups,
  1e6 offset, no effect, strong effect, and ten groups.
- The extra 126 integrated studentized-range CDF and 48 R quantile rows are
  retained unchanged; they are not substituted for the requested ANOVA/Tukey CI.

The task's tolerances are retained. B1: mean/SD/SEM relative 1e-12, CI relative
1e-10. B2: t absolute 1e-12, Student df exact, Welch df absolute 1e-12, p relative
1e-9 (absolute 1e-15 if reference p<1e-12); difference/CI are additionally checked
at absolute 1e-10. B3: F absolute 1e-12, p absolute 1e-9, Tukey differences/CI
absolute 1e-10, Tukey adjusted p absolute 1e-6. Max relative errors are reported
as well. No original Prism test's looser tolerance or scaled-error definition is
adopted. The fixed CI check remains a genuine failing test if R's Tukey interval
and scipy's mathematically computed interval disagree beyond the limit.
