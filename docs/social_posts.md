# Social posts (post both; tag @TigerGraphDB; add the hashtag from the hhgoa.com notice board if one is required)

## LinkedIn

A risk score isn't a verdict. In the dataset for the @TigerGraph × Hacker House Goa challenge, most transactions
the bank's model scored above 0.7 were legitimate. Some real fraud scored near zero.

So instead of building another classifier, we built **FraudLens**: a team of AI investigators that works through
every alert on a TigerGraph knowledge graph.

🔎 Four specialist agents query TigerGraph through the official **TigerGraph MCP** server, with read-only access, using 17 installed GSQL queries.

🧠 **Graph memory, three ways:**
- we resolve the hidden cardholder account behind each card (entity resolution);
- hybrid GraphRAG runs TigerVector search inside a candidate set built by graph traversal;
- every investigation is written back to the graph.

⚖️ The fraud policy is code (R1–R10, case vs SAR, stop rule). For every alert the agent computes what to do if the
customer confirms, denies or doesn't reply, then asks for evidence before blocking on a weak signal.

🕸️ It found two fraud patterns the bank had never documented: purchases structured just under a $500 threshold, and a
Samsung device profile hitting 20 cardholders from behind an anonymous proxy.

✅ Every claim carries a GSQL query you can re-run live. The model predicts; TigerGraph proves.

Blog: <link> · Demo: <link> · Code: <link>

@TigerGraph #TigerGraph #GraphRAG #AgenticAI #FraudDetection #HackerHouseGoa

## X (Twitter), as a 3-post thread

1/ Most high-score fraud alerts are false alarms. We built FraudLens for the @TigerGraphDB × Hacker House Goa
challenge: AI investigators that work every alert on a TigerGraph knowledge graph and cite a re-runnable GSQL query
for every claim. 🧵

2/ Four specialist agents query TigerGraph through TigerGraph MCP (read-only). The fraud policy is code: verify before
blocking, case vs SAR, a stop rule. Hybrid GraphRAG = TigerVector search inside a graph-built candidate set. Every case
is written back as memory.

3/ It surfaced two patterns the bank had never documented: purchases structured just under $500, and one device ring
across 20 cards. The model predicts; TigerGraph proves. Blog: <link> · Demo: <link> #GraphRAG #AgenticAI
