Hello everyone, welcome to the demo presentation of Semdisc. Here, we are looking at the settings of the offline stage, where we can select different hyperparameter values for semdisc. We can also select a data lake of our choice that contains the CSV files. We will choose the 'orders' data lake first. Once we hit preprocess- semantic types, the join graph and the join path index will be created.

Here, on the left, we can browse the extracted semantic types of the tables by clicking on this dropdown. In the middle, we can browse all indexed join paths, viewing the tables involved, the number of rows, and the number of columns produced. (change selection of join path). For a selected join path, we can view it as a connected graph of nodes representing tables and edges representing joinable column pairs. On the left, we see a heatmap of the indexed join paths, binned by the number of tuples and the number of tables involved. A darker shade in a bin indicates more join paths in that bin. (click on a heatmap cell) We can view the join paths for any bin by simply clicking a cell in the heatmap.

Now, let's submit a query table. (click on query table button). We can input our query table by adding rows and columns along with semantic types. For demonstration, I will load a prepopulated query here (click the dropdown and select it). In this query, we specify that we want to build a table from the data lake using semdisc, with an order ID column, a customer ID column, and a country column. Next, we hit submit (click Submit Query Table).

We can now see the list of join paths that can produce our query table. Here, we highlight all join paths in blue, which can produce all query rows. For a selected join path, we can see that the highlighted light-green nodes are the tables that contain the columns of our query table. 

We can select a column to see which table it belongs to. We can also select rows in the query table to see which join paths produce each row (click a row). Here, the green-highlighted paths can fully produce our selected row. 

We can navigate the join paths through the same hitmap. (Click on the hitmap cell until a yellow join path comes). Here, a yellow join path indicates that not all query rows can be retrieved via that path.

We can materialize the join path and download the CSV file to serve as our dataset.

I will show one more example from our other data lake 'country'. We will follow the same procedure. (continue clicking until we reach the query table)

Here, we will give semdisc a query table containing country, currency, and continent. We submit the query table.
(click on submit)
 And semdisc will again find the join paths that can generate a table containing the tuples from our query table. We can download any materialized table from the join paths as a dataset.
