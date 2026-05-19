Look at the paper nldisc_demo_paper.md

The current UI is a simulated UI with fake data.
We need to implement a backend that can be connected to it.
Read the paper and give a plan to implement the backend.
Your plan should have the following things included.

1) The code to extract table descriptions using openai API is missing. you need to implement that by reading the paper.

2) The code to suggest the first query tables based on the natural language query and table descriptions is also missing. You need to implement that by reading the paper.

3) The code to submit corrected query table and get new suggestion of query tables is also missing. You need to implement that reading the paper.

4) In the natural language query, you need to show a buttom to 'Populate a sample query' dropdown, that will show query 1 and query 2. If I press on a query, a natural languag query will be populated in the previously empty field of the natural language query.

5) All fake data hardcoded in the code must be removed. You are not allowed to remove any frontend component (showing fake data or not) unless specified in this plan.

6) Implement a completely working backend based on what is required in the UI. You have to look at the current UI and code to make the plan to implement the backend. All backend will be in a backend folder served by a flask API, run by a project-local prefixed conda environment. You have to make sure that the backend implementation will serve necessary information to populate all the components of the UI with real data. The code for the backend will be kept under a 'backend' folder. Make sure to write a requirements.txt file as well that will use pip under the conda environment to install dependencies.

7) You need to write test cases for backend only to make sure that the whole NLDisc method works. You may modify the data lake tables to serve your purpose as needed. You may create natural language queries that go well with your implementation of the paper. The test cases that you will write will ultimately be shown in the UI. So make sure that the test cases cover everything without needing a UI, but will be inspired by the UI design and paper.

8) You will need to replace the upload csv feature of the frontend with a dropdown that will show the data lake names already kept in datalake. Each folder will contain CSV files of that data lake. When you do preprocessing- save all preprocessed data in preprocessed_data/<datalake> to avoid repeated future computations for the same data.

9) For the openai api key, I have put it in backend/.env, which you will need to read and use. All API calls will be cached under files with hash names based on the prompt to avoid API costs for duplicate prompts.

10) The folder semdisc_broken_codes contains files that have been copied to this folder. These files do not have a working code, but they have the algorithms needed to be implemented. Make sure to follow the algorithms with your own implementation. NLDisc repeatedly mentions using semdisc algorithms.

semdisc_broken_codes/join_graph.py contains all related code to building the join graph.

semdisc_broken_codes/pairwise_simple_path_index.py contains all related code to building the join path inverted index.

semdisc_broken_codes/precompute_all_join_paths_minhashes.py contains how Minhash is used.

semdisc_broken_codes/semantic_type_extractor.py contains how semantic types are extracted for each column.

SemDisc uses semantic joins. In NLDisc, we will focus only on equi-joins.

11) You are not supposed to write any python code in the plan. Only write plans. No need to write any python code that you will eventually write after the planning phase. However, make all extensive plan needed. Your backend test cases will guide the integrity of the implementation. Your plan name will be backend_integration_plan.md that will be under the project root.

