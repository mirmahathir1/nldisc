Hello everyone, welcome to the demo presentation of NLDisc. NLDisc lets a user describe a desired joined dataset in plain English and then discovers a join path through a CSV data lake that produces that dataset for them. We are looking at the Offline Stage, where we can pick a data lake of our choice and tune four thresholds that govern preprocessing — semantic-type similarity, semantic joinability, equi-joinability, and maximum join path length.

We will start with our `country` data lake. (Click the Data Lake dropdown and select `country`.) The card immediately summarizes the lake- listing each table with its row count. The four threshold sliders become enabled at their defaults. We will leave the sliders as they are and hit **Run preprocessing**. (Click Run preprocessing.)

Behind the scenes, NLDisc is asking OpenAI to extract semantic types for every column, write a one-sentence description for every table, and then embedding the descriptions and the join paths with MPNet. (Wait for spinner to finish.) Once it is done, on the left we see the discovered join paths summarised as cards, and on the right we see the LLM-written one-line description for every table. We now click **Go to Online Stage**. (Click Go to Online Stage.)

In the Online Stage we describe our target dataset in natural language. I will load a prepopulated query here. (Click the `Populate a sample query` dropdown and select `Query 1`.) The textarea fills with the query *"Show countries with currency, continent, GDP per capita, population, literacy rate, and life expectancy."* We hit **Generate query tables**. (Click Generate query tables.)

After a few seconds, NLDisc returns four candidate query tables, each rendered as a card with three example rows. The first card is selected by default. Notice that NLDisc has translated our sentence into structured columns — Country, Currency, Continent, GDP Per Capita, Population, Literacy Rate, Life Expectancy — and has filled in plausible example values so we can verify intent before we commit.

Now I want to enrich the query with one more attribute. (Click `Add column` on the first card.) A new column appears. I will rename it to `gini_coefficient` and type a few representative values. (Rename column, then type `41.5`, `30.5`, `33.7`.) I hit **Resubmit**. (Click Resubmit.) NLDisc revises the suggestions while preserving my edit on the first card, and the new round of suggestions reflects that `gini_coefficient` should be drawn from the `gini_index` table.

Once I am satisfied, I hit **Confirm**. (Click Confirm.) The right column now populates with three sections — a list of discovered join paths, a SQL card, and a materialized table preview. NLDisc has figured out from my confirmed rows that the answer involves six tables — `GDP_Per_Capita_Completed`, `census_data`, `continent_mapping`, `literacy_rates`, `health_indicators`, and `gini_index` — all sharing the `country` column as their join key.

For a selected join path we can see it rendered as a small graph of nodes, with the tables that satisfy our query columns highlighted. (Click a different path card.) The SQL card and the materialized preview both refresh to reflect the newly selected path.

We can see that our new added column is present in the final table. Finally, we click **Download CSV** to save the projected dataset to disk. (Click Download CSV.)

I will now show one more example with our other data lake, `orders`. (Click the Data Lake dropdown and select `orders`.) We follow the same flow — run preprocessing, go to the Online Stage, and pick the sample query. (Click Run preprocessing, then Go to Online Stage, then select Query 1.) The query here is *"Show orders with customer country, ordered products, quantities, categories, and shipment carriers."* We hit **Generate**. (Click Generate query tables.)

NLDisc returns four suggestions. I will add one more column to the first card — this time, `order_date`, with values like `2025-12-10`, `2025-12-11`, `2025-12-20`. (Add the column and type the values.) I resubmit, confirm, and the right column fills in with join paths, SQL, and the projected preview. (Click Resubmit, then Confirm.)

The top path here is `jp_00069`, which chains `categories → products → order_items → orders → customers`. The projected materialized table shows exactly the six columns we asked for — order ID, customer country, product, quantity, category, carrier — plus our newly added order date, each one drawn from the lake column whose semantic type best matched our query column. (Click Download CSV.)

And that is NLDisc. From a single natural-language sentence — plus optional edits — we get a confirmed query table, discovered join paths, and a downloadable dataset. Thank you.
