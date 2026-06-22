"""行业基准数据 — LTV/CAC/留存率等私有指标的估算和基准值

设计原则:
  1. 所有基准值必须标注来源，附带"不代表公司披露"声明
  2. 支持按公司类型（SaaS/B2B/Consumer）和阶段的细分基准
  3. 提供公式推算函数（LTV, CAC 等）
  4. 所有基准输出 confidence_level="benchmark"
  5. 区分"披露信息挖掘"和"行业均值填充"两条路径

数据来源:
  - SaaS: OpenView/Tom Tunguz/KeyBanc SaaS Survey (2024)
  - B2B Enterprise: BCG/Bain/McKinsey 公开研究
  - Consumer: Sequoia/a16z 公开博客数据
"""

from __future__ import annotations

# ── 行业基准数据 ──

BENCHMARKS: dict[str, dict] = {
    "saas": {
        "retention_month1": {
            "value": "60%–80%",
            "range_low": 60,
            "range_high": 80,
            "unit": "%",
            "source": "OpenView SaaS Benchmarks 2024",
            "year": 2024,
            "note": "月1留存，中位数~70%",
        },
        "retention_month12": {
            "value": "40%–60%",
            "range_low": 40,
            "range_high": 60,
            "unit": "%",
            "source": "Tom Tunguz SaaS Metrics 2024",
            "year": 2024,
            "note": "年留存，中位数~50%",
        },
        "churn_monthly": {
            "value": "3%–7%",
            "range_low": 3,
            "range_high": 7,
            "unit": "%",
            "source": "KeyBanc SaaS Survey 2024",
            "year": 2024,
            "note": "月流失率中位数~5%",
        },
        "churn_annual": {
            "value": "30%–55%",
            "range_low": 30,
            "range_high": 55,
            "unit": "%",
            "source": "KeyBanc SaaS Survey 2024",
            "year": 2024,
        },
        "ltv_cac_ratio": {
            "seed": {"value": "2.5x–3.5x", "source": "SaaS Capital 2024", "year": 2024},
            "series_a": {"value": "3x–5x", "source": "OpenView SaaS Benchmarks 2024", "year": 2024},
            "series_b": {"value": "3x–6x", "source": "OpenView SaaS Benchmarks 2024", "year": 2024},
            "series_c_plus": {"value": "4x–8x", "source": "SaaS Capital 2024", "year": 2024},
            "default": {"value": "3x–5x", "source": "OpenView SaaS Benchmarks 2024", "year": 2024},
        },
        "gross_margin": {
            "value": "70%–80%",
            "range_low": 70,
            "range_high": 80,
            "unit": "%",
            "source": "KeyBanc SaaS Survey 2024",
            "year": 2024,
        },
        "cac_range": {
            "value": "$500–$5,000",
            "source": "SaaS Capital / OpenView 2024",
            "year": 2024,
            "note": "取决于 ACV，SMB $100-500, Mid-Market $500-5k, Enterprise $5k-50k",
        },
        "payback_months": {
            "value": "6–18 月",
            "source": "SaaS Capital 2024",
            "year": 2024,
        },
    },
    "b2b": {
        "retention_annual": {
            "value": "85%–95%",
            "range_low": 85,
            "range_high": 95,
            "unit": "%",
            "source": "BCG Enterprise Software Study 2023",
            "year": 2023,
            "note": "年合约续约率 (NRR)",
        },
        "ltv_cac_ratio": {
            "seed": {"value": "2x–3x", "source": "Bain Enterprise SaaS 2023", "year": 2023},
            "series_a": {"value": "3x–4x", "source": "Bain Enterprise SaaS 2023", "year": 2023},
            "series_b": {"value": "3x–5x", "source": "Bain Enterprise SaaS 2023", "year": 2023},
            "series_c_plus": {"value": "4x–6x", "source": "Bain Enterprise SaaS 2023", "year": 2023},
            "default": {"value": "3x–5x", "source": "Bain Enterprise SaaS 2023", "year": 2023},
        },
        "gross_margin": {
            "value": "60%–75%",
            "range_low": 60,
            "range_high": 75,
            "unit": "%",
            "source": "BCG Enterprise Software Study 2023",
            "year": 2023,
        },
        "cac_range": {
            "value": "$5,000–$50,000",
            "source": "BCG Enterprise SaaS 2023",
            "year": 2023,
        },
    },
    "consumer": {
        "retention_month1": {
            "value": "20%–40%",
            "range_low": 20,
            "range_high": 40,
            "unit": "%",
            "source": "Sequoia Consumer Tech 2024",
            "year": 2024,
            "note": "消费级产品月1留存显著低于SaaS",
        },
        "retention_month12": {
            "value": "5%–15%",
            "range_low": 5,
            "range_high": 15,
            "unit": "%",
            "source": "Sequoia Consumer Tech 2024",
            "year": 2024,
        },
        "ltv_cac_ratio": {
            "seed": {"value": "1.5x–2.5x", "source": "a16z Consumer 2024", "year": 2024},
            "series_a": {"value": "2x–3x", "source": "Sequoia Consumer Tech 2024", "year": 2024},
            "series_b": {"value": "2.5x–4x", "source": "Sequoia Consumer Tech 2024", "year": 2024},
            "series_c_plus": {"value": "3x–5x", "source": "a16z Consumer 2024", "year": 2024},
            "default": {"value": "2x–3x", "source": "Sequoia Consumer Tech 2024", "year": 2024},
        },
        "cac_range": {
            "value": "$1–$50",
            "source": "Sequoia/a16z Consumer 2024",
            "year": 2024,
            "note": "消费级获客成本低，重 viral/organic",
        },
    },
}

# 默认流失率（用于无数据时的 LTV 估算）
DEFAULT_CHURN_RATES = {
    "saas": 0.05,       # 月 5%
    "b2b": 0.03,        # 月 3%（企业级更稳）
    "consumer": 0.08,   # 月 8%
    "default": 0.05,
}

DISCLAIMER = "行业基准，不代表公司披露"


def get_benchmark(category: str, metric_key: str) -> dict:
    """获取指定品类和指标的行业基准。

    Returns:
        {"value": ..., "source": "...", "year": ..., "disclaimer": "...", "confidence_level": "benchmark"}
        或 {"value": None, "confidence_level": "unavailable", "reason": "..."}
    """
    cat_data = BENCHMARKS.get(category)
    if cat_data is None:
        return {
            "value": None,
            "confidence_level": "unavailable",
            "reason": f"未知品类: {category}",
            "disclaimer": DISCLAIMER,
        }

    entry = cat_data.get(metric_key)
    if entry is None:
        return {
            "value": None,
            "confidence_level": "unavailable",
            "reason": f"未知指标: {category}.{metric_key}",
            "disclaimer": DISCLAIMER,
        }

    return {
        "value": entry.get("value"),
        "source": entry.get("source", ""),
        "year": entry.get("year"),
        "note": entry.get("note", ""),
        "disclaimer": DISCLAIMER,
        "confidence_level": "benchmark",
    }


def get_retention_benchmark(company_type: str = "saas") -> dict:
    """获取留存率行业基准。

    返回 month-1 留存值，带 source 和 disclaimer。
    """
    cat = company_type if company_type in BENCHMARKS else "saas"
    result = get_benchmark(cat, "retention_month1")
    # 如果品类没有 month-1 留存（如 B2B 只有年留存），回退到 SaaS
    if result["value"] is None and cat != "saas":
        result = get_benchmark("saas", "retention_month1")
    result["confidence_level"] = "benchmark"
    return result


def get_ltv_cac_benchmark(company_type: str = "saas", stage: str = "default") -> dict:
    """获取 LTV/CAC 比率行业基准。

    按公司类型和融资阶段细分。
    """
    cat = company_type if company_type in BENCHMARKS else "saas"
    bench_data = BENCHMARKS[cat].get("ltv_cac_ratio", {})
    entry = bench_data.get(stage, bench_data.get("default", {}))
    if not entry:
        return {
            "value": None,
            "source": "",
            "year": None,
            "confidence_level": "unavailable",
            "disclaimer": DISCLAIMER,
            "reason": f"无 {cat}/{stage} 基准数据",
        }
    return {
        "value": entry.get("value"),
        "source": entry.get("source", ""),
        "year": entry.get("year"),
        "confidence_level": "benchmark",
        "disclaimer": DISCLAIMER,
    }


def estimate_ltv(
    monthly_price: float | None = None,
    annual_price: float | None = None,
    monthly_churn_rate: float | None = None,
    company_type: str = "saas",
) -> dict:
    """推算 LTV（生命周期价值）。

    LTV = 月均收入 × 平均生命周期月数
    平均生命周期月数 = 1 / 月流失率

    Args:
        monthly_price: 月定价
        annual_price: 年定价（自动转为月均）
        monthly_churn_rate: 月流失率 (0.0-1.0)
        company_type: 公司类型，用于回退流失率基准

    Returns:
        {"ltv": float|None, "formula": str, "confidence_level": str,
         "assumed_churn_rate": float|None, "disclaimer": str, "reason": str|None}
    """
    # 确定月均收入
    mrr_per_customer = None
    if monthly_price is not None and monthly_price > 0:
        mrr_per_customer = monthly_price
    elif annual_price is not None and annual_price > 0:
        mrr_per_customer = annual_price / 12.0

    if mrr_per_customer is None:
        return {
            "ltv": None,
            "formula": "LTV = 月均收入 × (1 / 月流失率)",
            "confidence_level": "unavailable",
            "assumed_churn_rate": None,
            "disclaimer": DISCLAIMER,
            "reason": "缺少定价信息，无法推算 LTV",
        }

    # 确定月流失率
    assumed_churn = None
    if monthly_churn_rate is not None and monthly_churn_rate > 0:
        assumed_churn = monthly_churn_rate
    else:
        assumed_churn = DEFAULT_CHURN_RATES.get(company_type, DEFAULT_CHURN_RATES["default"])

    avg_lifetime_months = 1.0 / assumed_churn
    ltv = round(mrr_per_customer * avg_lifetime_months, 2)

    churn_note = ""
    if monthly_churn_rate is None:
        churn_note = f"，流失率使用{company_type}行业基准 {assumed_churn*100:.0f}%/月"

    return {
        "ltv": ltv,
        "formula": f"LTV = ${mrr_per_customer}/月 × (1 / {assumed_churn})月 = ${ltv}",
        "confidence_level": "estimated",
        "assumed_churn_rate": assumed_churn,
        "disclaimer": f"公式推算{churn_note}。{DISCLAIMER}",
        "reason": None,
    }


def estimate_cac(
    monthly_ad_spend: float | None = None,
    new_customers_per_month: int | None = None,
    company_type: str = "saas",
) -> dict:
    """推算 CAC（获客成本）。

    CAC = 月营销支出 / 月新增客户数
    如果无法推算，返回行业基准区间。

    Args:
        monthly_ad_spend: 月营销支出（估算）
        new_customers_per_month: 月新增客户数（估算）
        company_type: 公司类型
    """
    if monthly_ad_spend is not None and new_customers_per_month is not None \
            and new_customers_per_month > 0:
        cac = round(monthly_ad_spend / new_customers_per_month, 2)
        return {
            "cac": cac,
            "formula": f"CAC = ${monthly_ad_spend} / {new_customers_per_month} = ${cac}",
            "confidence_level": "estimated",
            "disclaimer": f"公式推算，基于估算输入。{DISCLAIMER}",
            "reason": None,
        }
    else:
        # 返回行业基准
        result = get_benchmark(company_type, "cac_range")
        result["formula"] = "CAC 无法推算（缺少广告支出/客户数），使用行业基准"
        return result
