# DE lab cutouts (A4)

- `DE_Verilog_Cutouts_A4.pdf`: 29 cutouts on 16 sheets (Experiments 7–10, design + testbench)
- `DE_Logisim_Cutouts_A4.pdf`: 5 figure cutouts on 3 sheets

Print at **Actual size / 100%**, single-sided. Every cutout is 17 cm wide and
neighbours share one dashed line, so: cut down both long sides once, cut across
each dashed line, then paste in the order of the black numbers.

Regenerate:

    pdftotext -layout Verilog_Code_Compact.pdf v.txt
    python3 extract_verilog.py v.txt verilog_source.txt
    pdfimages -png DE_logism_figures.pdf figs/fig
    python3 make_cutouts.py verilog_source.txt figs .
