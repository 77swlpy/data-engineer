# Q2.4 - 慢查询优化分析

## 原始 SQL

```sql
SELECT 
    c.customer_state,
    COUNT(DISTINCT o.order_id) AS orders,
    SUM(oi.price) AS revenue,
    AVG(r.review_score) AS avg_score
FROM orders o
LEFT JOIN customers c ON o.customer_id = c.customer_id
LEFT JOIN order_items oi ON o.order_id = oi.order_id
LEFT JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01'
  AND LOWER(c.customer_city) LIKE '%sao%'
GROUP BY c.customer_state
ORDER BY revenue DESC;
```

---

## 第 1 问：性能问题分析（至少 3 个）

### 问题 1：
LEFT JOIN order_items oi ON o.order_id = oi.order_id
LEFT JOIN order_reviews r ON o.order_id = r.order_id
此处数据直接合并了数据会多出很多重复数据，应该像前几问一样加入去重步骤

### 问题 2：

COUNT(DISTINCT o.order_id)
使用 DISTINCT 的原因是多表连接之后，一个订单可能对应多条记录。
数据库在完成关联后，需要额外识别每个州中不同的订单 ID，再进行计数。
直接修改为：
COUNT(*) AS orders

### 问题 3：

LOWER(c.customer_city)
对索引列使用函数，使普通 B-Tree 索引无法直接用于该表达式的范围查找，增加逐行计算开销。
LIKE '%sao%' 查询条件以 % 开头，即使 customer_city 存在普通 B-Tree 索引，也无法进行有效的索引范围查找。
---

## 第 2 问：优化方案

### 优化后的 SQL

```sql
WITH /* q24_after */ filtered_orders AS (
    SELECT
        o.order_id,
        c.customer_state
    FROM `olist`.`olist_orders_dataset.csv` AS o
    INNER JOIN `olist`.`olist_customers_dataset.csv` AS c
        ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND c.customer_city LIKE '%sao%'
),

item_totals AS (
    SELECT
        oi.order_id,
        SUM(oi.price) AS order_revenue
    FROM `olist`.`olist_order_items_dataset.csv` AS oi
    INNER JOIN filtered_orders AS f
        ON oi.order_id = f.order_id
    GROUP BY oi.order_id
),

review_totals AS (
    SELECT
        r.order_id,
        SUM(r.review_score) AS score_sum,
        COUNT(r.review_score) AS score_count
    FROM `olist`.`olist_order_reviews_dataset.csv` AS r
    INNER JOIN filtered_orders AS f
        ON r.order_id = f.order_id
    GROUP BY r.order_id
)

SELECT
    f.customer_state,
    COUNT(*) AS orders,
    SUM(i.order_revenue) AS revenue,
    SUM(r.score_sum)
        / NULLIF(SUM(r.score_count), 0) AS avg_score
FROM filtered_orders AS f
LEFT JOIN item_totals AS i
    ON f.order_id = i.order_id
LEFT JOIN review_totals AS r
    ON f.order_id = r.order_id
GROUP BY f.customer_state
ORDER BY revenue DESC;
```

### 优化前 vs 优化后实测对比

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 执行时间 |1.4856 | 4.1540|
| 扫描行数 | 341,884| 236,277|

**这里卡住了，明明是修改了弱化性能的部分，为什么性能反而降低了？**
ai说是因为预聚合改写减少了检查行数，并修正了多表连接造成的金额重复累计，但本次测试未获得性能提升。检查行数下降不代表整体执行成本下降，具体瓶颈仍需结合执行计划确认。
---

## 第 3 问：潜在的统计错误（关键题）

> `SUM(oi.price)` 的结果可能不是你以为的「订单总收入」。为什么？
原始 SQL 同时通过 order_id 关联商品明细表和评价表，但是这三张表的数据粒度不同
当一个订单包含 N 条商品明细和 M 条评价，且两侧均有匹配记录时，直接关联会产生 N* M条记录，导致每条商品金额被重复计算 M 次。


**修正方案**：

```sql
WITH

-- 1. 筛选满足业务条件的订单
filtered_orders AS (
    SELECT
        o.order_id,
        c.customer_state
    FROM `olist`.`olist_orders_dataset.csv` AS o
    INNER JOIN `olist`.`olist_customers_dataset.csv` AS c
        ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND LOWER(c.customer_city) LIKE '%sao%'
),

-- 2. 将商品明细聚合至订单级
-- 保证每个订单的商品金额仅被计算一次
order_revenue AS (
    SELECT
        oi.order_id,
        SUM(oi.price) AS order_revenue
    FROM `olist`.`olist_order_items_dataset.csv` AS oi
    INNER JOIN filtered_orders AS f
        ON oi.order_id = f.order_id
    GROUP BY oi.order_id
),

-- 3. 按订单ID和评价ID去重
-- 延续Q2.3的评价处理方案
-- MAX使用前提：同一订单—评价组合内评分一致
review_dedup AS (
    SELECT
        r.order_id,
        r.review_id,
        MAX(r.review_score) AS review_score
    FROM `olist`.`olist_order_reviews_dataset.csv` AS r
    INNER JOIN filtered_orders AS f
        ON r.order_id = f.order_id
    WHERE r.review_score BETWEEN 1 AND 5
    GROUP BY
        r.order_id,
        r.review_id
),

-- 4. 计算订单内平均评分
-- 避免多评价订单或多商品订单获得额外权重
order_review AS (
    SELECT
        order_id,
        AVG(review_score) AS order_review_score
    FROM review_dedup
    GROUP BY order_id
)

-- 5. 在统一的订单粒度下进行州级汇总
SELECT
    f.customer_state,

    COUNT(*) AS orders,

    SUM(rev.order_revenue) AS revenue,

    ROUND(AVG(r.order_review_score), 4) AS avg_score

FROM filtered_orders AS f

LEFT JOIN order_revenue AS rev
    ON f.order_id = rev.order_id

LEFT JOIN order_review AS r
    ON f.order_id = r.order_id

GROUP BY f.customer_state

ORDER BY revenue DESC;
```
