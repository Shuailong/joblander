"""练兵场：题库自校验 + 判题器行为。

题库正确性是这页的生命线——测试集错了会把正确解误判成错，
所以每题的 ref 参考解必须全过自己的用例。
"""
import pytest

from joblander.drill import PROBLEMS, get_problem, random_problem, run_drill


def test_bank_integrity():
    ids = [p["id"] for p in PROBLEMS]
    assert len(ids) == len(set(ids)), "题目 id 重复"
    for p in PROBLEMS:
        assert p["tests"], p["id"]
        assert "class Solution" in p["signature"], p["id"]
        assert p["method"] in p["signature"], p["id"]
        assert p["hint"] and p["pattern"] and p["desc"], p["id"]


@pytest.mark.parametrize("p", PROBLEMS, ids=[p["id"] for p in PROBLEMS])
def test_reference_solutions_pass(p):
    r = run_drill(p["id"], p["ref"])
    fails = [c for c in r.get("cases", []) if not c["pass"]]
    assert r["verdict"] == "pass", (p["id"], r.get("error"), fails[:2])


def test_wrong_answer_detected():
    r = run_drill("jump-game", "class Solution:\n    def canJump(self, nums):\n        return True\n")
    assert r["verdict"] == "fail" and 0 < r["passed"] < r["total"]
    bad = next(c for c in r["cases"] if not c["pass"])
    assert bad["expected"] == "false" and bad["got"] == "true"


def test_syntax_error_reported():
    r = run_drill("jump-game", "class Solution\n    def broken(")
    assert r["verdict"] == "error" and "SyntaxError" in r["error"]


def test_runtime_error_per_case():
    r = run_drill("jump-game",
                  "class Solution:\n    def canJump(self, nums):\n        return nums[99] > 0\n")
    assert r["verdict"] == "fail"
    assert any("IndexError" in c["err"] for c in r["cases"])


def test_timeout_killed():
    r = run_drill("jump-game",
                  "class Solution:\n    def canJump(self, nums):\n"
                  "        while True: pass\n", timeout=2)
    assert r["verdict"] == "timeout" and "超时" in r["error"]


def test_input_mutation_isolated():
    # 用户代码就地改输入（sort/淹岛）不得污染后续比较——判题器逐用例 deepcopy
    code = ("class Solution:\n"
            "    def canJump(self, nums):\n"
            "        nums.clear() or nums.append(1)\n"
            "        reach = 0\n"
            "        return True\n")
    r = run_drill("jump-game", code)
    assert r["total"] == len(get_problem("jump-game")["tests"])


def test_unordered_compare():
    # canonical：外内层顺序都不限（3Sum 倒序返回也算对）
    code = ("class Solution:\n"
            "    def threeSum(self, nums):\n"
            "        nums.sort(); res = []\n"
            "        for i in range(len(nums) - 2):\n"
            "            if i and nums[i] == nums[i-1]: continue\n"
            "            l, r = i + 1, len(nums) - 1\n"
            "            while l < r:\n"
            "                s = nums[i] + nums[l] + nums[r]\n"
            "                if s < 0: l += 1\n"
            "                elif s > 0: r -= 1\n"
            "                else:\n"
            "                    res.append([nums[r], nums[l], nums[i]][::-1])\n"
            "                    l += 1\n"
            "                    while l < r and nums[l] == nums[l-1]: l += 1\n"
            "                    r -= 1\n"
            "        return list(reversed(res))\n")
    assert run_drill("three-sum", code)["verdict"] == "pass"


def test_random_problem_excludes():
    for _ in range(20):
        assert random_problem(exclude="three-sum")["id"] != "three-sum"


def test_unknown_and_empty():
    assert run_drill("nope", "x = 1")["ok"] is False
    assert run_drill("jump-game", "   ")["ok"] is False
