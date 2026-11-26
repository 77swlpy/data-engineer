/* ============================================================
   Q2.2
   --注意点：1.处理异常值
   -- 2.避免重复（1对多）数据不能只是简单合并
   -- 3.状态判断
    ============================================================ */
-- ① 查看订单表字段
SHOW COLUMNS
FROM `olist`.`olist_orders_dataset.csv`;
-- ② 查看订单明细表字段
SHOW COLUMNS
FROM `olist`.`olist_order_items_dataset.csv`;

-- 可以发现订单表的 order_id 为主键；下单时间、客户收货时间及订单状态均允许 NULL
-- 下一步检查异常数据
-- Q2.2 数据核查第一步：按订单状态检查时间质量
-- 以下主要核查不同订单状态下的时间缺失、时间倒置和下单时间范围
SELECT
    order_status,

    COUNT(*) AS order_count,

    COUNT(
        CASE
            WHEN order_purchase_timestamp IS NULL
            THEN 1
        END
    ) AS missing_purchase_time,

    COUNT(
        CASE
            WHEN order_delivered_customer_date IS NULL
            THEN 1
        END
    ) AS missing_delivery_time,

    COUNT(
        CASE
            WHEN order_delivered_customer_date
                 < order_purchase_timestamp
            THEN 1
        END
    ) AS negative_delivery_time,

    MIN(order_purchase_timestamp) AS first_purchase_time,
    MAX(order_purchase_timestamp) AS last_purchase_time

FROM `olist`.`olist_orders_dataset.csv`

GROUP BY order_status
ORDER BY order_count DESC;
-- 显示有 8 条 delivered 订单缺少收货时间，有 6 条 canceled 订单填写了收货时间（这些属于异常值）
-- 假设：本题以数据集记录的订单状态作为业务指标分类依据。对于订单状态与收货时间存在冲突的记录，仅进行异常标记，不根据时间字段擅自修改订单状态。

-- 下一步检查订单明细的金额质量，以及订单与明细之间的关联完整性

-- ① 将明细核查结果汇总到订单粒度，再按状态统计。
WITH item_check AS (
    SELECT
        order_id,
        COUNT(*) AS item_count,
        COUNT(CASE WHEN price IS NULL THEN 1 END)
            AS missing_price_items,
        COUNT(CASE WHEN freight_value IS NULL THEN 1 END)
            AS missing_freight_items,
        COUNT(CASE WHEN price < 0 THEN 1 END)
            AS negative_price_items,
        COUNT(CASE WHEN freight_value < 0 THEN 1 END)
            AS negative_freight_items
    FROM `olist`.`olist_order_items_dataset.csv`
    GROUP BY order_id
)
SELECT
    o.order_status,
    COUNT(*) AS order_count,
    COUNT(CASE WHEN i.order_id IS NULL THEN 1 END)
        AS orders_without_items,
    COUNT(CASE WHEN i.item_count > 1 THEN 1 END)
        AS multi_item_orders,
    COUNT(CASE WHEN i.missing_price_items > 0 THEN 1 END)
        AS orders_missing_price,
    COUNT(CASE WHEN i.missing_freight_items > 0 THEN 1 END)
        AS orders_missing_freight,
    COUNT(CASE WHEN i.negative_price_items > 0 THEN 1 END)
        AS orders_negative_price,
    COUNT(CASE WHEN i.negative_freight_items > 0 THEN 1 END)
        AS orders_negative_freight
FROM `olist`.`olist_orders_dataset.csv` AS o
LEFT JOIN item_check AS i
    ON o.order_id = i.order_id
GROUP BY o.order_status
ORDER BY order_count DESC;
-- ② 反向检查：是否有明细找不到所属订单。
SELECT
    COUNT(*) AS orphan_item_rows,
    COUNT(DISTINCT i.order_id) AS orphan_order_ids
FROM `olist`.`olist_order_items_dataset.csv` AS i
LEFT JOIN `olist`.`olist_orders_dataset.csv` AS o
    ON i.order_id = o.order_id
WHERE o.order_id IS NULL;

-- 将商品明细汇总到订单粒度，再按下单月份计算七个指标，同时保留金额异常和有效时长样本数供核查
WITH item_summary AS (
    -- 第一层：将商品明细汇总到订单粒度，同时记录金额异常。
    SELECT
        order_id,

        COUNT(
            CASE
                WHEN price IS NULL OR freight_value IS NULL
                THEN 1
            END
        ) AS missing_amount_items,

        COUNT(
            CASE
                WHEN price < 0 OR freight_value < 0
                THEN 1
            END
        ) AS negative_amount_items,

        -- 这里只计算中间值。
        -- 如果存在金额异常，下一层会将整个订单金额设为 NULL。
        SUM(price + freight_value) AS amount_sum

    FROM `olist`.`olist_order_items_dataset.csv`
    GROUP BY order_id
),

order_level AS (
    -- 第二层：以订单表为主表，每个订单保持一行。
    SELECT
        o.order_id,
        DATE_FORMAT(
            o.order_purchase_timestamp, '%Y-%m'
        ) AS order_month,
        o.order_status,

        CASE WHEN i.order_id IS NULL
             THEN 1 ELSE 0 END AS missing_items,

        CASE WHEN i.missing_amount_items > 0
             THEN 1 ELSE 0 END AS missing_amount,

        CASE WHEN i.negative_amount_items > 0
             THEN 1 ELSE 0 END AS negative_amount,

        -- 无明细、金额缺失或负金额未核实：订单金额为未知。
        CASE
            WHEN i.order_id IS NULL
              OR i.missing_amount_items > 0
              OR i.negative_amount_items > 0
            THEN NULL
            ELSE i.amount_sum
        END AS order_gmv,

        -- 只有满足时长计算条件的已送达订单才返回秒数。
        -- 其他订单返回 NULL，但仍保留在订单级记录中。
        CASE
            WHEN o.order_status = 'delivered'
             AND o.order_purchase_timestamp IS NOT NULL
             AND o.order_delivered_customer_date IS NOT NULL
             AND o.order_delivered_customer_date
                 >= o.order_purchase_timestamp
            THEN TIMESTAMPDIFF(
                SECOND,
                o.order_purchase_timestamp,
                o.order_delivered_customer_date
            )
            ELSE NULL
        END AS delivery_seconds

    FROM `olist`.`olist_orders_dataset.csv` AS o
    LEFT JOIN item_summary AS i
        ON o.order_id = i.order_id
),

monthly_summary AS (
    -- 第三层：在订单粒度上计算月度统计。
    SELECT
        order_month,
        COUNT(*) AS total_orders,

        COUNT(
            CASE WHEN order_status = 'delivered' THEN 1 END
        ) AS delivered_orders,

        COUNT(
            CASE WHEN order_status = 'canceled' THEN 1 END
        ) AS canceled_orders,

        -- 用于判断该月已送达 GMV 是否完整。
        COUNT(
            CASE
                WHEN order_status = 'delivered'
                 AND order_gmv IS NULL
                THEN 1
            END
        ) AS invalid_gmv_orders,

        -- 金额异常原因，供辅助核查使用。
        COUNT(
            CASE
                WHEN order_status = 'delivered'
                 AND missing_items = 1
                THEN 1
            END
        ) AS delivered_without_items,

        COUNT(
            CASE
                WHEN order_status = 'delivered'
                 AND missing_amount = 1
                THEN 1
            END
        ) AS delivered_missing_amount,

        COUNT(
            CASE
                WHEN order_status = 'delivered'
                 AND negative_amount = 1
                THEN 1
            END
        ) AS delivered_negative_amount,

        -- SUM 会忽略 NULL，因此最终输出必须结合异常数量判断。
        SUM(
            CASE
                WHEN order_status = 'delivered' THEN order_gmv
                ELSE 0
            END
        ) AS delivered_amount_sum,

        COUNT(delivery_seconds) AS valid_delivery_orders,
        AVG(delivery_seconds) AS avg_delivery_seconds

    FROM order_level
    GROUP BY order_month
)

SELECT
    COALESCE(order_month, '月份未知') AS `month`,
    total_orders,
    delivered_orders,
    canceled_orders,

    -- 单位为百分数：例如 1.25 表示 1.25%。
    ROUND(
        100.0 * canceled_orders / NULLIF(total_orders, 0),
        2
    ) AS cancel_rate,

    CASE
        WHEN delivered_orders = 0 THEN 0.00
        WHEN invalid_gmv_orders > 0 THEN NULL
        ELSE ROUND(delivered_amount_sum, 2)
    END AS delivered_gmv,

    -- 先平均秒数再换算为天，与逐单换算后平均等价，
    -- 避免对每个订单的天数提前舍入。
    ROUND(
        avg_delivery_seconds / 86400.0,
        2
    ) AS avg_delivery_days

FROM monthly_summary
ORDER BY order_month IS NULL, order_month;

