# Intent-aware Join Discovery using Natural Language

**Mir Mahathir Mohammad**
University of Utah
mahathir.mohammad@utah.edu

**El Kindi Rezig**
University of Utah
elkindi.rezig@utah.edu

---

## ABSTRACT

We present NLDisc, a system for intent-aware join discovery over data lakes using natural language (NL) queries. Unlike existing data discovery systems that rely on structured inputs (e.g., example tables) or fail to support join operations for NL queries, NLDisc enables users to describe their desired datasets in natural language—automatically discovering relevant join paths across multiple tables. NLDisc addresses key challenges in NL-based data discovery by supporting interactive intent disambiguation. We demonstrate NLDisc's capabilities across diverse real-world data lakes, including benchmarks and public datasets. A companion video is available at [3].

## 1 INTRODUCTION

Data lakes are now pervasive, from public repositories (e.g., US Government Open Data [1]) to private platforms (e.g., MIT Data Warehouse [2]). Yet, building datasets from them remains a major obstacle. Unlike traditional databases, data lakes lack explicit schemas (e.g., primary/foreign keys), forcing users to manually interpret table contents and relationships. Despite advances in data discovery tools [8, 10, 11], current data discovery systems rely on query tables or structured queries and lack natural language (NL) interfaces for discovering joined datasets, while also failing to model ambiguity in user intent.

**Example:** Consider the example in Figure 1 ① where a data scientist, Lou, writes a natural language query of the dataset they want to build. Ideally, Lou expects the following requirements to be supported by the data discovery system:

**(R1) Query by natural language:** Because Lou is unfamiliar with the values in the data lake, they elect to use a natural language interface where they only describe the target dataset they want to build. Existing data discovery systems that support a natural language interface [13] are only limited to finding individual tables in the data lake that match the user's query and do not perform join discovery.

**(R2) Intent disambiguation:** Because natural language queries come with an inherent ambiguity, the data discovery system should allow Lou to clarify ambiguities in the query. For instance, in Figure 1 ③, we can see that all three tables could be valid interpretations of the user's query.

**(R3) Diversification of Join Paths:** Existing approaches [10] focus exclusively on content overlap with the query table to identify join paths, often producing results that are semantically redundant and contain duplicate content. To better address user needs, a system must account for the semantic similarity among join paths without incurring the cost of expensive materialization, thereby returning a diverse set of join paths that are relevant to the user's needs.

**Contributions.** We present NLDisc, which extends SemDisc [10] with support for natural language queries, enabling users to interactively explore join paths using natural language queries. Specifically, NLDisc: (1) automatically discovers relevant join paths from NL queries; (2) unlike NL2SQL approaches that return a SQL query for an NL query, NLDisc translates the NL query into a structured, interpretable representation (a query table), which users can refine to better express their intent; and (3) diversifies join paths based on semantic similarity.

**Related work.** Various data discovery techniques have explored different interfaces to enable users to automatically discover data from data lakes. DICE [11] enables users to discover equi-joins using an example table, and Aurum [8] allows queries using a structured language, and then discovers equi-joins across data lake columns. DeepJoin [6], WarpGate [5], and SemDisc [10] can discover semantic join paths across tables given a query column. However, none of the existing join discovery techniques support a natural language query. Another related line of work is NL2SQL [7], where the goal is to generate a SQL query for a given NL query. However, unlike NLDisc, these techniques (1) are not designed for data lakes where there is no pre-defined schema; and (2) do not allow users to disambiguate their intent. Finally, a recent NL data discovery system was proposed [13]; however, unlike NLDisc, (1) it only generates queries for a single table (no joins), and (2) like the NL2SQL techniques, it does not allow intent disambiguation.

## 2 SYSTEM OVERVIEW

Figure 2 illustrates the workflow of NLDisc. NLDisc operates in two phases: (1) **Offline Phase:** NLDisc extracts descriptions from data lake tables and constructs a table description index to retrieve candidate tables via semantic similarity with the user's natural language query (Figure 2 ①). Additionally, NLDisc builds join path embeddings based on their semantic types. (2) **Online Phase:** When a user submits a natural language query, NLDisc first suggests candidate query tables for the user to assess; the user may select, modify, and resubmit until a satisfactory query table is obtained (Figure 2 ②). Once the user's intent has been disambiguated through the final query table, the system retrieves the top-k join paths from a join path index and diversifies the results based on join path embeddings (Figure 2 ③).

### 2.1 Building Semantic Indexes

This section describes the offline phase of NLDisc, in which NLDisc extracts semantic descriptions of tables from the data lake and constructs a join path index to efficiently retrieve join paths for a given set of candidate tables.

**Generating Table Description Index:** NLDisc identifies candidate tables that are semantically similar to a natural language query. To enable this, NLDisc uses an LLM (GPT-5.1 [4]) to generate a single-sentence natural language description for each table, which can then be used for comparison and candidate selection. The prompt for extracting table descriptions is structured as follows:

**Instruction:** A directive specifying that the LLM should generate a natural language description for a table.

```
You are given a table name, column semantic types, and example values.
Table name: regional_sales
Table Metadata: <Table Metadata>
Write a single, concise, natural-language sentence that explains what the table
contains. The description should be human-readable. Keep each description to one
sentence and avoid bullet points or numbering.
```

**Output Format:** The output is an NL description of the table.

```
The table contains the regional sales of units.
```

**Input Table Metadata:** Columns are listed one per line, each with its identifier, semantic type, and sample values.

```
column 1 Semantic Type: Region Names
Example Values: West Region, East Region, ...
column 2 ...
```

After collecting all table descriptions, NLDisc uses MPNet [12] to compute embeddings for each description and indexes these embeddings using a Hierarchical Navigable Small World (HNSW) [9] index to enable fast approximate nearest neighbor search.

During the offline phase, NLDisc leverages SemDisc's [10] join detection engine to identify both equi-joins and semantic joins. Specifically, NLDisc extracts semantic types and detects table relationships based on Jaccard similarity between column sketches using SemDisc [10]. The detected relationships form a join graph, where nodes correspond to data lake tables and edges connect joinable column pairs. From this graph, NLDisc enumerates all simple join paths and encodes them into a join path index represented as a binary matrix: rows correspond to tables, columns correspond to join paths, and a cell value of 1 indicates that the table participates in the corresponding path. We refer the reader to SemDisc [10] for further details on the join detection and indexing process.

**Building Join Path Embeddings:** During the online phase, NLDisc returns join paths based on their diversity. Given a set of candidate join paths, NLDisc filters out those that are too similar (containing similar tables) and ranks the remaining paths so that diverse paths appear earlier in the top-K results. Unlike existing approaches [10], which do not attempt to diversify the returned join paths, NLDisc constructs a semantic representation for each join path using semantic types and embeddings.

To create a representative embedding for each join path, NLDisc simulates materialization using only the column names. Specifically, NLDisc extracts MPNet embeddings for the semantic types of all columns in the path and computes their mean embedding vector. These per-path embeddings are then used to identify diverse join paths and avoid presenting redundant join paths to the user.

### 2.2 Disambiguating User Intent

This section describes the online phase of NLDisc, in which the system accepts a natural language query and disambiguates user intent through an iterative process. NLDisc suggests sample table representations called *Query Tables* and incorporates user feedback to refine these suggestions, leveraging tables from the data lake to produce increasingly personalized results.

Upon receiving a natural language query, NLDisc extracts its MPNet embedding and retrieves the most relevant tables from the HNSW index of semantic table description embeddings. These tables serve as the initial set of candidate tables, which are provided as context for the LLM to generate query tables.

**LLM-Assisted Query Table Generation:** NLDisc prompts an LLM (GPT-5.1 [4]) to generate sample query tables that help disambiguate user intent. The prompt is structured as follows:

**Instruction:** A directive specifying that the LLM should generate a user-specified number of query tables.

```
You are given a list of context tables, their column semantic types, and sample
values. The user has provided a natural language description of a table they want
the system to produce from the context tables (by joining multiple tables if
necessary).
Suggest <User-specified number> sample tables with 3 rows that could be produced
from the context tables, aligned with the user's natural language query.
User Query: <User Query>
<Context Tables>
<Output Format>
```

**Context Tables:** The context tables are provided to the LLM along with their column semantic types and example values.

```
Table 1: <Table Name>
Column 1 Semantic Type: <Semantic Type>
Column 1 Example Values: <List of 10 most frequent values>
...
```

**Output Format:** The prompt instructs the LLM to return query tables as a JSON array:

```
Only reply with a response that follows the JSON format specified below:
[{"table": "Query 1",
  "content": [
    {"semantic type": <column semantic type>,
     "examples": [<example 1>, <example 2>, ...]
    }, ...]...
```

**Refining Query Tables:** After generating the initial query tables, NLDisc presents them to the user for selection and refinement. Users can add, edit, or remove rows and columns from their selected query table and resubmit it to NLDisc. The system then identifies data lake tables with overlapping semantic types and values, and uses these as context for subsequent LLM-assisted query table generation. This iterative process continues until the user finalizes a query table. Through this workflow, users curate their desired output while NLDisc simultaneously refines the set of candidate tables required for joining.

### 2.3 Retrieving Join Paths

**Querying the Join Path Index:** During the online phase, NLDisc uses the join path index to retrieve paths containing the candidate tables. Once the user finalizes a query table, NLDisc queries the index by identifying columns where all corresponding candidate table rows contain 1s, and retrieves all join paths that involve all candidate tables.

**Diversifying Join Paths:** NLDisc leverages join path embeddings to diversify the results returned from the index, selecting a final set of *K* diverse join paths from the initial join path candidates. This diversification follows a two-step process:

**(1) Semantic Deduplication:** NLDisc initializes an empty list of deduplicated join paths and iterates through all the paths containing the candidate tables. For each path, NLDisc computes the cosine similarity between its embedding and those of all paths already in the deduplicated list. If the cosine similarity exceeds a threshold (~0.8) with any existing path, the current path is discarded; otherwise, it is added to the deduplicated list.

**(2) Diversification:** NLDisc applies *K*-means clustering with *K* centroids to the embeddings of the deduplicated join paths. For each cluster, only the join path whose embedding is closest to the centroid is selected, yielding the final set of *K* diverse join paths returned to the user.

## 3 DEMONSTRATION PLAN

We demonstrate NLDisc on the following data lakes: (1) **Spider (SP)**, a benchmark for Text-to-SQL tasks, adapted by selecting 156 databases containing join queries and removing schema information to test join recovery; (2) **LakeBench (LB)**, a benchmark for data discovery, where the join subset (OpenData) provides ground truth column pairs that can be joined; (3) **DrugCentral (DC)**, a curated online resource with comprehensive drug-related data; (4) **U.S. Fish and Wildlife Service (FWS)**, a data lake with geographic, behavioral, and ecological records of flora and fauna across the U.S.; and (5) **Centers for Disease Control and Prevention (CDC)**, which includes public health datasets such as disease incidence, mortality, and drug usage statistics sourced from data.gov.

**Demonstration outline.** In this demonstration, SIGMOD participants will be able to discover datasets from the above data lakes by interacting with NLDisc at key points, including (1) asking natural language queries and interactively disambiguating their intent through the suggested query tables; (2) examining the returned join paths and the source tables they used to match the query. We now present two demonstration scenarios for the participants to observe the inner workings of NLDisc.

### Scenario 1: Offline Phase

In this scenario, participants can adjust various settings of the offline phase and observe how NLDisc constructs the indexes required for the online phase.

**① Data Lake Upload:** Users initiate the system by uploading CSV files comprising the data lake through the NLDisc web interface (Figure 3 ①). This action triggers the Offline Phase, during which NLDisc preprocesses the data lake and constructs the join path index, table description index and join path embeddings. This preprocessing step is performed only once, and participants can configure hyperparameters for building the join path index to customize the similarity thresholds for identifying joinable columns.

**② Exploring Curated Join Paths:** Participants can examine the complete list of join paths indexed by NLDisc during the offline phase (Figure 3 ②). Each join path displays its estimated cardinality, attribute list, hop count, and a visualization representing tables as nodes and joinable column pairs as edges.

**③ Table Descriptions:** Users can view the LLM-generated table descriptions within NLDisc (Figure 3 ③). Each description consists of a single natural-language sentence, accompanied by an MPNet embedding representation, indexed in an HNSW index.

### Scenario 2: Online Phase

Participants can load a preprocessed data lake and initiate the online phase by specifying a natural language prompt, ultimately constructing a dataset through intent disambiguation.

**Ⓐ Query Specification:** Participants pose their natural language queries through the interface (Figure 3 Ⓐ). The user describes the desired table to be constructed by leveraging the available data lake tables through the natural language query.

**Ⓑ Intent Disambiguation:** NLDisc enables users to disambiguate their intent by presenting a set of candidate query tables (Figure 3 Ⓑ). These query tables serve as previews of what the final constructed dataset will contain.

**Ⓒ Editing Query Tables:** Users can refine the candidate tables to clarify their intent—for example, by adding, editing, or deleting values, rows, or columns (Figure 3 Ⓒ)—thereby personalizing the dataset construction process. These edits directly influence the tuples and attributes that will appear in the materialized table.

**Ⓓ Resubmit or Confirm Query Table:** After modifying a query table, users can click 'Resubmit' to generate new candidate query tables from NLDisc (Figure 3 Ⓓ). Users may iteratively select, modify, and resubmit query tables to obtain additional suggestions, or confirm the selected query table to proceed with join path retrieval.

**Ⓔ Retrieved Diverse Join Paths:** Upon confirmation of a query table, NLDisc presents a ranked list of diverse join paths (Figure 3 Ⓔ). Each join path displays the same metadata as the indexed join paths from the offline phase, with nodes containing columns from the selected query table highlighted in yellow.

**Ⓕ Materializing a Join Path:** Users can select any retrieved join path by clicking on it, then view the corresponding SQL query (Figure 3 Ⓕ) and download the materialized table as a CSV file or a SQL query.

**Demonstration engagement.** Since NLDisc is an interactive system that requires human feedback (intent disambiguation), this demonstration will engage SIGMOD participants at various steps of the join discovery process. More importantly, SIGMOD participants will be able to dissect the unique ambiguity challenges that arise in join discovery when we use natural language as the query interface.

## REFERENCES

- [1] [n.d.]. The Home of the U.S. Government's Open Data. https://data.gov/.
- [2] [n.d.]. MITDWH. https://ist.mit.edu/warehouse.
- [3] [n.d.]. NLDisc demo video. https://drive.google.com/drive/folders/10WmQjZ6qH27dsUYIfQ2n0IeN9D94MTb0?usp=sharing
- [4] Josh Achiam, Steven Adler, Sandhini Agarwal, Lama Ahmad, Ilge Akkaya, Florencia Leoni Aleman, Diogo Almeida, Janko Altenschmidt, Sam Altman, Shyamal Anadkat, et al. 2023. Gpt-4 technical report. *arXiv preprint arXiv:2303.08774* (2023).
- [5] Tianji Cong, James Gale, Jason Frantz, HV Jagadish, and Çağatay Demiralp. 2022. Warpgate: A semantic join discovery system for cloud data warehouses. *arXiv preprint arXiv:2212.14155* (2022).
- [6] Yuyang Dong, Chuan Xiao, Takuma Nozawa, Masafumi Enomoto, and Masafumi Oyamada. 2022. Deepjoin: Joinable table discovery with pre-trained language models. *arXiv preprint arXiv:2212.07588* (2022).
- [7] Ju Fan, Zihui Gu, Songyue Zhang, Yuxin Zhang, Zui Chen, Lei Cao, Guoliang Li, Samuel Madden, Xiaoyong Du, and Nan Tang. 2024. Combining Small Language Models and Large Language Models for Zero-Shot NL2SQL. *Proc. VLDB Endow.* 17, 11 (2024), 2750–2763. https://doi.org/10.14778/3681954.3681960
- [8] Raul Castro Fernandez, Ziawasch Abedjan, Famien Koko, Gina Yuan, Samuel Madden, and Michael Stonebraker. 2018. Aurum: A data discovery system. In *2018 IEEE 34th International Conference on Data Engineering (ICDE)*. IEEE, 1001–1012.
- [9] Yu A. Malkov and D. A. Yashunin. 2020. Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs. *IEEE Trans. Pattern Anal. Mach. Intell.* 42, 4 (April 2020), 824–836. https://doi.org/10.1109/TPAMI.2018.2889473
- [10] Mir Mahathir Mohammad and El Kindi Rezig. 2026. Qualitative Join Discovery in Data Lakes using Examples. *Proceedings of the ACM on Management of Data* 4, 1, Article 68 (Mar 2026), 28 pages. https://mirmahathir.com/papers/semdisc.pdf
- [11] El Kindi Rezig, Anshul Bhandari, Anna Fariha, Benjamin Price, Allan Vanterpool, Vijay Gadepally, and Michael Stonebraker. 2021. DICE: data discovery by example. *Proceedings of the VLDB Endowment* 14, 12 (2021), 2819–2822.
- [12] Kaitao Song, Xu Tan, Tao Qin, Jianfeng Lu, and Tie-Yan Liu. 2020. MPNet: masked and permuted pre-training for language understanding. In *Proceedings of the 34th International Conference on Neural Information Processing Systems (Vancouver, BC, Canada) (NIPS '20)*. Curran Associates Inc., Red Hook, NY, USA, Article 1414, 11 pages.
- [13] Qiming Wang and Raul Castro Fernandez. [n.d.]. Solo: Data Discovery Using Natural Language Questions Via A Self-Supervised Approach. *SIGMOD* ([n.d.]).
