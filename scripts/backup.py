import argparse,sqlite3
parser=argparse.ArgumentParser();parser.add_argument("source");parser.add_argument("destination");args=parser.parse_args()
with sqlite3.connect(args.source) as source,sqlite3.connect(args.destination) as destination: source.backup(destination)
with sqlite3.connect(args.destination) as restored:
    assert restored.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
print(f"Backup verified: {args.destination}")

