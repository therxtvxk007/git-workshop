"""Turn `pdftotext -layout` output of Verilog_Code_Compact.pdf into clean source.

Output format (verilog_source.txt):
    @@ EXPERIMENT <n> | <title>
    @@ ITEM <circuit title>
    @@ FILE <name.v>
    <code lines>
"""
import re
import sys

STRAY = {"S", "D", "CLK"}  # one-letter labels that leaked into the code in the PDF

HALF_ADDER = """\
// Data flow
module half_adder_df (input A, B, output Sum, Cout);
  assign Sum = A ^ B;
  assign Cout = A & B;
endmodule
// Behavioural
module half_adder_bh (input A, B, output reg Sum, Cout);
  always @(*) begin
    if (A ^ B)
      Sum = 1;
    else
      Sum = 0;
    if (A & B)
      Cout = 1;
    else
      Cout = 0;
  end
endmodule""".splitlines()


def main(src, dst):
    lines = open(src).read().replace("\f", "\n").splitlines()
    out, cur_file, skip_half_adder = [], None, False
    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not s or re.fullmatch(r"\d+/\d+", s) or s in STRAY:
            continue
        m = re.fullmatch(r"EXPERIMENT (\d+) - (.+)", s)
        if m:
            out.append(f"@@ EXPERIMENT {m[1]} | {m[2].title()}")
            continue
        if re.fullmatch(r"\([A-H]\) .+", s) or s == "Half adder":
            out.append(f"@@ ITEM {s}")
            continue
        m = re.fullmatch(r"(\w+\.v)( \(cont\.\))?", s)
        if m:
            skip_half_adder = False
            if not m[2]:
                cur_file = m[1]
                out.append(f"@@ FILE {cur_file}")
                if cur_file == "half_adder.v":
                    out.extend(HALF_ADDER)
                    skip_half_adder = True
            continue
        if skip_half_adder:
            continue
        # a $monitor string that the PDF wrapped mid-literal: rejoin it
        if out and out[-1].count('"') % 2 == 1:
            out[-1] = out[-1] + " " + s
            continue
        out.append(line)
    open(dst, "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
