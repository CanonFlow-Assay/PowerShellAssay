import sys

label = sys.argv[1]
print(label)
raise SystemExit(7 if label == "reject" else 0)
