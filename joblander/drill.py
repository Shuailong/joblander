"""练兵场：LeetCode Medium 手感训练。

题库内置在本模块（经典题型、原创题面、带测试集），随机出题；
运行 = 子进程执行用户代码对全部用例，超时强杀。一期只支持 Python3。

每题带 ref 参考解，测试套件用它自校验题库——测试集错了会在 CI 先炸，
不会让正确解在练习时被误判。
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_S = 8
STDOUT_CAP = 2000

# cmp 模式：
#   exact     —— 逐项相等
#   outer     —— 外层列表顺序不限，内层顺序算答案（permutations / merge intervals）
#   canonical —— 内外层顺序都不限（three-sum / group-anagrams / top-k）
PROBLEMS: list[dict] = [
    {
        "id": "three-sum", "title": "3Sum", "pattern": "排序 + 双指针",
        "hint": "排序后固定最小位，双指针夹逼其余两位；三处都要跳过重复值去重。",
        "desc": "Given an integer array nums, return all unique triplets "
                "[a, b, c] in nums such that a + b + c == 0. "
                "The solution set must not contain duplicate triplets.",
        "examples": [("nums = [-1,0,1,2,-1,-4]", "[[-1,-1,2],[-1,0,1]]"),
                     ("nums = [0,1,1]", "[]")],
        "constraints": ["3 <= len(nums) <= 3000", "-10^5 <= nums[i] <= 10^5"],
        "method": "threeSum", "cmp": "canonical",
        "signature": "class Solution:\n    def threeSum(self, nums: list[int]) -> list[list[int]]:\n        ",
        "tests": [
            {"args": [[-1, 0, 1, 2, -1, -4]], "expected": [[-1, -1, 2], [-1, 0, 1]]},
            {"args": [[0, 1, 1]], "expected": []},
            {"args": [[0, 0, 0]], "expected": [[0, 0, 0]]},
            {"args": [[-2, 0, 1, 1, 2]], "expected": [[-2, 0, 2], [-2, 1, 1]]},
        ],
        "ref": (
            "class Solution:\n"
            "    def threeSum(self, nums):\n"
            "        nums.sort(); res = []\n"
            "        for i in range(len(nums) - 2):\n"
            "            if i and nums[i] == nums[i - 1]: continue\n"
            "            l, r = i + 1, len(nums) - 1\n"
            "            while l < r:\n"
            "                s = nums[i] + nums[l] + nums[r]\n"
            "                if s < 0: l += 1\n"
            "                elif s > 0: r -= 1\n"
            "                else:\n"
            "                    res.append([nums[i], nums[l], nums[r]])\n"
            "                    l += 1\n"
            "                    while l < r and nums[l] == nums[l - 1]: l += 1\n"
            "                    r -= 1\n"
            "        return res\n"),
    },
    {
        "id": "container-water", "title": "Container With Most Water", "pattern": "双指针",
        "hint": "两端向内夹逼，每步移动较矮的一侧——矮边决定水位，动高边不可能更优。",
        "desc": "Given an array height where height[i] is the height of the i-th "
                "vertical line, choose two lines that together with the x-axis form "
                "a container holding the most water. Return the maximum amount.",
        "examples": [("height = [1,8,6,2,5,4,8,3,7]", "49"), ("height = [1,1]", "1")],
        "constraints": ["2 <= len(height) <= 10^5", "0 <= height[i] <= 10^4"],
        "method": "maxArea", "cmp": "exact",
        "signature": "class Solution:\n    def maxArea(self, height: list[int]) -> int:\n        ",
        "tests": [
            {"args": [[1, 8, 6, 2, 5, 4, 8, 3, 7]], "expected": 49},
            {"args": [[1, 1]], "expected": 1},
            {"args": [[4, 3, 2, 1, 4]], "expected": 16},
            {"args": [[1, 2, 1]], "expected": 2},
        ],
        "ref": (
            "class Solution:\n"
            "    def maxArea(self, height):\n"
            "        l, r, best = 0, len(height) - 1, 0\n"
            "        while l < r:\n"
            "            best = max(best, (r - l) * min(height[l], height[r]))\n"
            "            if height[l] < height[r]: l += 1\n"
            "            else: r -= 1\n"
            "        return best\n"),
    },
    {
        "id": "longest-substring", "title": "Longest Substring Without Repeating Characters",
        "pattern": "滑动窗口",
        "hint": "窗口 + 每个字符最近出现位置；遇到窗口内重复字符就把左界跳到它的下一位。",
        "desc": "Given a string s, find the length of the longest substring "
                "without duplicate characters.",
        "examples": [("s = \"abcabcbb\"", "3"), ("s = \"bbbbb\"", "1")],
        "constraints": ["0 <= len(s) <= 5 * 10^4", "s consists of English letters, digits, symbols and spaces"],
        "method": "lengthOfLongestSubstring", "cmp": "exact",
        "signature": "class Solution:\n    def lengthOfLongestSubstring(self, s: str) -> int:\n        ",
        "tests": [
            {"args": ["abcabcbb"], "expected": 3},
            {"args": ["bbbbb"], "expected": 1},
            {"args": ["pwwkew"], "expected": 3},
            {"args": [""], "expected": 0},
            {"args": ["abba"], "expected": 2},
        ],
        "ref": (
            "class Solution:\n"
            "    def lengthOfLongestSubstring(self, s):\n"
            "        seen, start, best = {}, 0, 0\n"
            "        for i, c in enumerate(s):\n"
            "            if c in seen and seen[c] >= start: start = seen[c] + 1\n"
            "            seen[c] = i\n"
            "            best = max(best, i - start + 1)\n"
            "        return best\n"),
    },
    {
        "id": "search-rotated", "title": "Search in Rotated Sorted Array", "pattern": "二分查找",
        "hint": "每次二分必有一半有序；判断 target 是否落在有序半边内，决定往哪半走。",
        "desc": "An ascending array with distinct values was rotated at an unknown "
                "pivot. Given the rotated array nums and a target, return the index "
                "of target, or -1 if absent. Required: O(log n) runtime.",
        "examples": [("nums = [4,5,6,7,0,1,2], target = 0", "4"),
                     ("nums = [4,5,6,7,0,1,2], target = 3", "-1")],
        "constraints": ["1 <= len(nums) <= 5000", "all values are unique"],
        "method": "search", "cmp": "exact",
        "signature": "class Solution:\n    def search(self, nums: list[int], target: int) -> int:\n        ",
        "tests": [
            {"args": [[4, 5, 6, 7, 0, 1, 2], 0], "expected": 4},
            {"args": [[4, 5, 6, 7, 0, 1, 2], 3], "expected": -1},
            {"args": [[1], 0], "expected": -1},
            {"args": [[1, 3], 3], "expected": 1},
            {"args": [[5, 1, 3], 5], "expected": 0},
        ],
        "ref": (
            "class Solution:\n"
            "    def search(self, nums, target):\n"
            "        l, r = 0, len(nums) - 1\n"
            "        while l <= r:\n"
            "            m = (l + r) // 2\n"
            "            if nums[m] == target: return m\n"
            "            if nums[l] <= nums[m]:\n"
            "                if nums[l] <= target < nums[m]: r = m - 1\n"
            "                else: l = m + 1\n"
            "            else:\n"
            "                if nums[m] < target <= nums[r]: l = m + 1\n"
            "                else: r = m - 1\n"
            "        return -1\n"),
    },
    {
        "id": "number-of-islands", "title": "Number of Islands", "pattern": "网格 DFS/BFS",
        "hint": "遍历格子，遇 \"1\" 计数 +1 并把整个连通块淹掉（置 \"0\"），别重复数。",
        "desc": "Given an m x n grid of \"1\" (land) and \"0\" (water), return the "
                "number of islands. An island is a group of adjacent lands "
                "(horizontally or vertically) surrounded by water.",
        "examples": [("grid = [[\"1\",\"1\",\"0\"],[\"1\",\"0\",\"0\"],[\"0\",\"0\",\"1\"]]", "2")],
        "constraints": ["1 <= m, n <= 300", "grid[i][j] is \"0\" or \"1\""],
        "method": "numIslands", "cmp": "exact",
        "signature": "class Solution:\n    def numIslands(self, grid: list[list[str]]) -> int:\n        ",
        "tests": [
            {"args": [[["1", "1", "1", "1", "0"], ["1", "1", "0", "1", "0"],
                       ["1", "1", "0", "0", "0"], ["0", "0", "0", "0", "0"]]], "expected": 1},
            {"args": [[["1", "1", "0", "0", "0"], ["1", "1", "0", "0", "0"],
                       ["0", "0", "1", "0", "0"], ["0", "0", "0", "1", "1"]]], "expected": 3},
            {"args": [[["0"]]], "expected": 0},
        ],
        "ref": (
            "class Solution:\n"
            "    def numIslands(self, grid):\n"
            "        n, m, cnt = len(grid), len(grid[0]), 0\n"
            "        for i in range(n):\n"
            "            for j in range(m):\n"
            "                if grid[i][j] == '1':\n"
            "                    cnt += 1\n"
            "                    stk = [(i, j)]; grid[i][j] = '0'\n"
            "                    while stk:\n"
            "                        x, y = stk.pop()\n"
            "                        for a, b in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):\n"
            "                            if 0 <= a < n and 0 <= b < m and grid[a][b] == '1':\n"
            "                                grid[a][b] = '0'; stk.append((a, b))\n"
            "        return cnt\n"),
    },
    {
        "id": "rotting-oranges", "title": "Rotting Oranges", "pattern": "多源 BFS",
        "hint": "所有烂橘子同时入队做多源 BFS，层数即分钟数；结束后还有新鲜橘子返回 -1。",
        "desc": "In a grid, 0 is empty, 1 is a fresh orange, 2 is a rotten orange. "
                "Every minute, fresh oranges 4-directionally adjacent to a rotten "
                "one become rotten. Return the minutes until no fresh orange "
                "remains, or -1 if impossible.",
        "examples": [("grid = [[2,1,1],[1,1,0],[0,1,1]]", "4"),
                     ("grid = [[2,1,1],[0,1,1],[1,0,1]]", "-1")],
        "constraints": ["1 <= m, n <= 10", "grid[i][j] in {0, 1, 2}"],
        "method": "orangesRotting", "cmp": "exact",
        "signature": "class Solution:\n    def orangesRotting(self, grid: list[list[int]]) -> int:\n        ",
        "tests": [
            {"args": [[[2, 1, 1], [1, 1, 0], [0, 1, 1]]], "expected": 4},
            {"args": [[[2, 1, 1], [0, 1, 1], [1, 0, 1]]], "expected": -1},
            {"args": [[[0, 2]]], "expected": 0},
            {"args": [[[1]]], "expected": -1},
        ],
        "ref": (
            "class Solution:\n"
            "    def orangesRotting(self, grid):\n"
            "        from collections import deque\n"
            "        n, m = len(grid), len(grid[0])\n"
            "        q, fresh = deque(), 0\n"
            "        for i in range(n):\n"
            "            for j in range(m):\n"
            "                if grid[i][j] == 2: q.append((i, j, 0))\n"
            "                elif grid[i][j] == 1: fresh += 1\n"
            "        t = 0\n"
            "        while q:\n"
            "            x, y, t = q.popleft()\n"
            "            for a, b in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):\n"
            "                if 0 <= a < n and 0 <= b < m and grid[a][b] == 1:\n"
            "                    grid[a][b] = 2; fresh -= 1; q.append((a, b, t + 1))\n"
            "        return -1 if fresh else t\n"),
    },
    {
        "id": "course-schedule", "title": "Course Schedule", "pattern": "拓扑排序",
        "hint": "建图算入度，入度 0 的进队；出队消边，最后能出队的课程数 == 总数即无环。",
        "desc": "There are numCourses courses labeled 0..numCourses-1. "
                "prerequisites[i] = [a, b] means course b must be taken before a. "
                "Return true if you can finish all courses.",
        "examples": [("numCourses = 2, prerequisites = [[1,0]]", "true"),
                     ("numCourses = 2, prerequisites = [[1,0],[0,1]]", "false")],
        "constraints": ["1 <= numCourses <= 2000", "0 <= len(prerequisites) <= 5000"],
        "method": "canFinish", "cmp": "exact",
        "signature": "class Solution:\n    def canFinish(self, numCourses: int, prerequisites: list[list[int]]) -> bool:\n        ",
        "tests": [
            {"args": [2, [[1, 0]]], "expected": True},
            {"args": [2, [[1, 0], [0, 1]]], "expected": False},
            {"args": [5, [[1, 0], [2, 1], [3, 2], [4, 3]]], "expected": True},
            {"args": [1, []], "expected": True},
        ],
        "ref": (
            "class Solution:\n"
            "    def canFinish(self, numCourses, prerequisites):\n"
            "        from collections import deque\n"
            "        indeg = [0] * numCourses\n"
            "        adj = [[] for _ in range(numCourses)]\n"
            "        for a, b in prerequisites:\n"
            "            adj[b].append(a); indeg[a] += 1\n"
            "        q = deque(i for i in range(numCourses) if not indeg[i])\n"
            "        seen = 0\n"
            "        while q:\n"
            "            u = q.popleft(); seen += 1\n"
            "            for v in adj[u]:\n"
            "                indeg[v] -= 1\n"
            "                if not indeg[v]: q.append(v)\n"
            "        return seen == numCourses\n"),
    },
    {
        "id": "coin-change", "title": "Coin Change", "pattern": "DP · 完全背包",
        "hint": "dp[a] = 凑出金额 a 的最少硬币数；每个金额枚举所有硬币转移，凑不出为无穷。",
        "desc": "Given coins of different denominations and an amount, return the "
                "fewest number of coins needed to make up that amount, or -1 if it "
                "cannot be made. You have an infinite supply of each coin.",
        "examples": [("coins = [1,2,5], amount = 11", "3"), ("coins = [2], amount = 3", "-1")],
        "constraints": ["1 <= len(coins) <= 12", "0 <= amount <= 10^4"],
        "method": "coinChange", "cmp": "exact",
        "signature": "class Solution:\n    def coinChange(self, coins: list[int], amount: int) -> int:\n        ",
        "tests": [
            {"args": [[1, 2, 5], 11], "expected": 3},
            {"args": [[2], 3], "expected": -1},
            {"args": [[1], 0], "expected": 0},
            {"args": [[186, 419, 83, 408], 6249], "expected": 20},
        ],
        "ref": (
            "class Solution:\n"
            "    def coinChange(self, coins, amount):\n"
            "        INF = float('inf')\n"
            "        dp = [0] + [INF] * amount\n"
            "        for a in range(1, amount + 1):\n"
            "            for c in coins:\n"
            "                if c <= a and dp[a - c] + 1 < dp[a]: dp[a] = dp[a - c] + 1\n"
            "        return -1 if dp[amount] == INF else dp[amount]\n"),
    },
    {
        "id": "lis", "title": "Longest Increasing Subsequence", "pattern": "DP / 二分",
        "hint": "tails[k] = 长度 k+1 的上升子序列的最小结尾；每个数二分找位置替换或追加。",
        "desc": "Given an integer array nums, return the length of the longest "
                "strictly increasing subsequence.",
        "examples": [("nums = [10,9,2,5,3,7,101,18]", "4"), ("nums = [7,7,7,7]", "1")],
        "constraints": ["1 <= len(nums) <= 2500", "-10^4 <= nums[i] <= 10^4"],
        "method": "lengthOfLIS", "cmp": "exact",
        "signature": "class Solution:\n    def lengthOfLIS(self, nums: list[int]) -> int:\n        ",
        "tests": [
            {"args": [[10, 9, 2, 5, 3, 7, 101, 18]], "expected": 4},
            {"args": [[0, 1, 0, 3, 2, 3]], "expected": 4},
            {"args": [[7, 7, 7, 7, 7]], "expected": 1},
            {"args": [[4, 10, 4, 3, 8, 9]], "expected": 3},
        ],
        "ref": (
            "class Solution:\n"
            "    def lengthOfLIS(self, nums):\n"
            "        import bisect\n"
            "        tails = []\n"
            "        for x in nums:\n"
            "            i = bisect.bisect_left(tails, x)\n"
            "            if i == len(tails): tails.append(x)\n"
            "            else: tails[i] = x\n"
            "        return len(tails)\n"),
    },
    {
        "id": "house-robber-ii", "title": "House Robber II", "pattern": "DP · 状态取舍",
        "hint": "环形 = 两个线性问题取最大：要么不抢第一间，要么不抢最后一间。",
        "desc": "Houses are arranged in a circle; adjacent houses cannot both be "
                "robbed (the first and last are adjacent). Given nums where nums[i] "
                "is the money in house i, return the maximum amount you can rob.",
        "examples": [("nums = [2,3,2]", "3"), ("nums = [1,2,3,1]", "4")],
        "constraints": ["1 <= len(nums) <= 100", "0 <= nums[i] <= 1000"],
        "method": "rob", "cmp": "exact",
        "signature": "class Solution:\n    def rob(self, nums: list[int]) -> int:\n        ",
        "tests": [
            {"args": [[2, 3, 2]], "expected": 3},
            {"args": [[1, 2, 3, 1]], "expected": 4},
            {"args": [[1, 2, 3]], "expected": 3},
            {"args": [[1]], "expected": 1},
        ],
        "ref": (
            "class Solution:\n"
            "    def rob(self, nums):\n"
            "        def line(a):\n"
            "            take = skip = 0\n"
            "            for x in a:\n"
            "                take, skip = skip + x, max(skip, take)\n"
            "            return max(take, skip)\n"
            "        if len(nums) == 1: return nums[0]\n"
            "        return max(line(nums[1:]), line(nums[:-1]))\n"),
    },
    {
        "id": "permutations", "title": "Permutations", "pattern": "回溯",
        "hint": "逐位选数：path 已选 + rest 可选；rest 空即收集一个排列。",
        "desc": "Given an array nums of distinct integers, return all possible "
                "permutations, in any order.",
        "examples": [("nums = [1,2,3]", "[[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]]")],
        "constraints": ["1 <= len(nums) <= 6", "all integers are unique"],
        "method": "permute", "cmp": "outer",
        "signature": "class Solution:\n    def permute(self, nums: list[int]) -> list[list[int]]:\n        ",
        "tests": [
            {"args": [[1, 2, 3]], "expected": [[1, 2, 3], [1, 3, 2], [2, 1, 3],
                                               [2, 3, 1], [3, 1, 2], [3, 2, 1]]},
            {"args": [[0, 1]], "expected": [[0, 1], [1, 0]]},
            {"args": [[1]], "expected": [[1]]},
        ],
        "ref": (
            "class Solution:\n"
            "    def permute(self, nums):\n"
            "        res = []\n"
            "        def bt(path, rest):\n"
            "            if not rest:\n"
            "                res.append(path); return\n"
            "            for i in range(len(rest)):\n"
            "                bt(path + [rest[i]], rest[:i] + rest[i + 1:])\n"
            "        bt([], nums)\n"
            "        return res\n"),
    },
    {
        "id": "word-search", "title": "Word Search", "pattern": "回溯 · 网格",
        "hint": "从每个格子起 DFS 逐字符匹配；进入时临时改格子防重踩，回溯时还原。",
        "desc": "Given an m x n board of characters and a word, return true if the "
                "word exists in the grid, formed by sequentially adjacent cells "
                "(horizontally or vertically). A cell may not be used twice.",
        "examples": [("board = [[\"A\",\"B\",\"C\",\"E\"],[\"S\",\"F\",\"C\",\"S\"],[\"A\",\"D\",\"E\",\"E\"]], word = \"ABCCED\"", "true")],
        "constraints": ["1 <= m, n <= 6", "1 <= len(word) <= 15"],
        "method": "exist", "cmp": "exact",
        "signature": "class Solution:\n    def exist(self, board: list[list[str]], word: str) -> bool:\n        ",
        "tests": [
            {"args": [[["A", "B", "C", "E"], ["S", "F", "C", "S"], ["A", "D", "E", "E"]],
                      "ABCCED"], "expected": True},
            {"args": [[["A", "B", "C", "E"], ["S", "F", "C", "S"], ["A", "D", "E", "E"]],
                      "SEE"], "expected": True},
            {"args": [[["A", "B", "C", "E"], ["S", "F", "C", "S"], ["A", "D", "E", "E"]],
                      "ABCB"], "expected": False},
            {"args": [[["A"]], "A"], "expected": True},
        ],
        "ref": (
            "class Solution:\n"
            "    def exist(self, board, word):\n"
            "        n, m = len(board), len(board[0])\n"
            "        def dfs(i, j, k):\n"
            "            if k == len(word): return True\n"
            "            if not (0 <= i < n and 0 <= j < m) or board[i][j] != word[k]:\n"
            "                return False\n"
            "            board[i][j] = '#'\n"
            "            ok = (dfs(i+1, j, k+1) or dfs(i-1, j, k+1)\n"
            "                  or dfs(i, j+1, k+1) or dfs(i, j-1, k+1))\n"
            "            board[i][j] = word[k]\n"
            "            return ok\n"
            "        return any(dfs(i, j, 0) for i in range(n) for j in range(m))\n"),
    },
    {
        "id": "merge-intervals", "title": "Merge Intervals", "pattern": "区间 · 排序",
        "hint": "按起点排序后线性扫；当前区间与结果尾部重叠就并入（取更大右端），否则新开。",
        "desc": "Given an array of intervals [start, end], merge all overlapping "
                "intervals and return the non-overlapping intervals covering the "
                "same ranges.",
        "examples": [("intervals = [[1,3],[2,6],[8,10],[15,18]]", "[[1,6],[8,10],[15,18]]"),
                     ("intervals = [[1,4],[4,5]]", "[[1,5]]")],
        "constraints": ["1 <= len(intervals) <= 10^4", "0 <= start <= end <= 10^4"],
        "method": "merge", "cmp": "outer",
        "signature": "class Solution:\n    def merge(self, intervals: list[list[int]]) -> list[list[int]]:\n        ",
        "tests": [
            {"args": [[[1, 3], [2, 6], [8, 10], [15, 18]]],
             "expected": [[1, 6], [8, 10], [15, 18]]},
            {"args": [[[1, 4], [4, 5]]], "expected": [[1, 5]]},
            {"args": [[[1, 4], [2, 3]]], "expected": [[1, 4]]},
            {"args": [[[5, 6], [1, 2]]], "expected": [[1, 2], [5, 6]]},
        ],
        "ref": (
            "class Solution:\n"
            "    def merge(self, intervals):\n"
            "        intervals.sort()\n"
            "        res = []\n"
            "        for s, e in intervals:\n"
            "            if res and s <= res[-1][1]: res[-1][1] = max(res[-1][1], e)\n"
            "            else: res.append([s, e])\n"
            "        return res\n"),
    },
    {
        "id": "top-k-frequent", "title": "Top K Frequent Elements", "pattern": "堆 / 桶计数",
        "hint": "Counter 计频后取前 k：堆 O(n log k)，或按频次分桶 O(n)。",
        "desc": "Given an integer array nums and an integer k, return the k most "
                "frequent elements, in any order. The answer is guaranteed to be "
                "unique.",
        "examples": [("nums = [1,1,1,2,2,3], k = 2", "[1,2]"), ("nums = [1], k = 1", "[1]")],
        "constraints": ["1 <= len(nums) <= 10^5", "k is in [1, number of distinct elements]"],
        "method": "topKFrequent", "cmp": "canonical",
        "signature": "class Solution:\n    def topKFrequent(self, nums: list[int], k: int) -> list[int]:\n        ",
        "tests": [
            {"args": [[1, 1, 1, 2, 2, 3], 2], "expected": [1, 2]},
            {"args": [[1], 1], "expected": [1]},
            {"args": [[4, 4, 4, 6, 6, 2], 2], "expected": [4, 6]},
        ],
        "ref": (
            "class Solution:\n"
            "    def topKFrequent(self, nums, k):\n"
            "        from collections import Counter\n"
            "        return [x for x, _ in Counter(nums).most_common(k)]\n"),
    },
    {
        "id": "daily-temperatures", "title": "Daily Temperatures", "pattern": "单调栈",
        "hint": "维护温度递减的下标栈；来一个更高温度就不断出栈结算等待天数。",
        "desc": "Given an array temperatures of daily temperatures, return an array "
                "answer where answer[i] is the number of days to wait after day i "
                "for a warmer temperature, or 0 if none.",
        "examples": [("temperatures = [73,74,75,71,69,72,76,73]", "[1,1,4,2,1,1,0,0]")],
        "constraints": ["1 <= len(temperatures) <= 10^5", "30 <= temperatures[i] <= 100"],
        "method": "dailyTemperatures", "cmp": "exact",
        "signature": "class Solution:\n    def dailyTemperatures(self, temperatures: list[int]) -> list[int]:\n        ",
        "tests": [
            {"args": [[73, 74, 75, 71, 69, 72, 76, 73]], "expected": [1, 1, 4, 2, 1, 1, 0, 0]},
            {"args": [[30, 40, 50, 60]], "expected": [1, 1, 1, 0]},
            {"args": [[30, 60, 90]], "expected": [1, 1, 0]},
            {"args": [[90]], "expected": [0]},
        ],
        "ref": (
            "class Solution:\n"
            "    def dailyTemperatures(self, temperatures):\n"
            "        res = [0] * len(temperatures)\n"
            "        stk = []\n"
            "        for i, t in enumerate(temperatures):\n"
            "            while stk and temperatures[stk[-1]] < t:\n"
            "                j = stk.pop(); res[j] = i - j\n"
            "            stk.append(i)\n"
            "        return res\n"),
    },
    {
        "id": "jump-game", "title": "Jump Game", "pattern": "贪心",
        "hint": "维护能到达的最远下标；扫到某位时若它已超出最远可达即失败。",
        "desc": "Given an array nums where nums[i] is your maximum jump length from "
                "index i, starting at index 0, return true if you can reach the "
                "last index.",
        "examples": [("nums = [2,3,1,1,4]", "true"), ("nums = [3,2,1,0,4]", "false")],
        "constraints": ["1 <= len(nums) <= 10^4", "0 <= nums[i] <= 10^5"],
        "method": "canJump", "cmp": "exact",
        "signature": "class Solution:\n    def canJump(self, nums: list[int]) -> bool:\n        ",
        "tests": [
            {"args": [[2, 3, 1, 1, 4]], "expected": True},
            {"args": [[3, 2, 1, 0, 4]], "expected": False},
            {"args": [[0]], "expected": True},
            {"args": [[2, 0, 0]], "expected": True},
        ],
        "ref": (
            "class Solution:\n"
            "    def canJump(self, nums):\n"
            "        reach = 0\n"
            "        for i, x in enumerate(nums):\n"
            "            if i > reach: return False\n"
            "            reach = max(reach, i + x)\n"
            "        return True\n"),
    },
    {
        "id": "group-anagrams", "title": "Group Anagrams", "pattern": "哈希 · 规范键",
        "hint": "同字母异序词共享同一个规范键（排序后的字符串或 26 计数元组），按键分桶。",
        "desc": "Given an array of strings strs, group the anagrams together. "
                "Return the groups in any order.",
        "examples": [("strs = [\"eat\",\"tea\",\"tan\",\"ate\",\"nat\",\"bat\"]",
                      "[[\"bat\"],[\"nat\",\"tan\"],[\"ate\",\"eat\",\"tea\"]]")],
        "constraints": ["1 <= len(strs) <= 10^4", "strs[i] consists of lowercase English letters"],
        "method": "groupAnagrams", "cmp": "canonical",
        "signature": "class Solution:\n    def groupAnagrams(self, strs: list[str]) -> list[list[str]]:\n        ",
        "tests": [
            {"args": [["eat", "tea", "tan", "ate", "nat", "bat"]],
             "expected": [["ate", "eat", "tea"], ["nat", "tan"], ["bat"]]},
            {"args": [[""]], "expected": [[""]]},
            {"args": [["a"]], "expected": [["a"]]},
        ],
        "ref": (
            "class Solution:\n"
            "    def groupAnagrams(self, strs):\n"
            "        from collections import defaultdict\n"
            "        d = defaultdict(list)\n"
            "        for s in strs:\n"
            "            d[''.join(sorted(s))].append(s)\n"
            "        return list(d.values())\n"),
    },
    {
        "id": "product-except-self", "title": "Product of Array Except Self", "pattern": "前缀积",
        "hint": "禁除法：先左往右填前缀积，再右往左乘后缀积，O(1) 额外空间。",
        "desc": "Given an integer array nums, return an array answer where "
                "answer[i] is the product of all elements of nums except nums[i]. "
                "You must not use division and must run in O(n).",
        "examples": [("nums = [1,2,3,4]", "[24,12,8,6]"), ("nums = [-1,1,0,-3,3]", "[0,0,9,0,0]")],
        "constraints": ["2 <= len(nums) <= 10^5", "products fit in a 32-bit integer"],
        "method": "productExceptSelf", "cmp": "exact",
        "signature": "class Solution:\n    def productExceptSelf(self, nums: list[int]) -> list[int]:\n        ",
        "tests": [
            {"args": [[1, 2, 3, 4]], "expected": [24, 12, 8, 6]},
            {"args": [[-1, 1, 0, -3, 3]], "expected": [0, 0, 9, 0, 0]},
            {"args": [[2, 3]], "expected": [3, 2]},
        ],
        "ref": (
            "class Solution:\n"
            "    def productExceptSelf(self, nums):\n"
            "        n = len(nums)\n"
            "        res = [1] * n\n"
            "        p = 1\n"
            "        for i in range(n):\n"
            "            res[i] = p; p *= nums[i]\n"
            "        p = 1\n"
            "        for i in range(n - 1, -1, -1):\n"
            "            res[i] *= p; p *= nums[i]\n"
            "        return res\n"),
    },
]

_BY_ID = {p["id"]: p for p in PROBLEMS}


def get_problem(pid: str) -> dict | None:
    return _BY_ID.get(pid)


def random_problem(exclude: str = "") -> dict:
    pool = [p for p in PROBLEMS if p["id"] != exclude] or PROBLEMS
    return random.choice(pool)


# 判题跑在独立子进程：用户代码语法错/死循环都伤不到服务进程。
# 结果走 result.json 回传，stdout 留给用户的 print 当调试输出。
_HARNESS = r"""
import json, time, traceback
from copy import deepcopy
from pathlib import Path

def _coerce(v):
    if isinstance(v, tuple): return [_coerce(x) for x in v]
    if isinstance(v, set): return sorted((_coerce(x) for x in v), key=repr)
    if isinstance(v, list): return [_coerce(x) for x in v]
    return v

def _norm(v, mode):
    v = _coerce(v)
    if mode in ("outer", "canonical") and isinstance(v, list):
        if mode == "canonical":
            v = [sorted(x, key=repr) if isinstance(x, list) else x for x in v]
        v = sorted(v, key=lambda x: json.dumps(x, default=repr))
    return v

spec = json.loads(Path("tests.json").read_text(encoding="utf-8"))
out = {"results": [], "error": ""}
try:
    import sol
    fn = getattr(sol.Solution(), spec["method"])
except Exception:
    out["error"] = traceback.format_exc(limit=3)
else:
    for case in spec["tests"]:
        r = {"pass": False, "got": None, "err": "", "ms": 0}
        try:
            t0 = time.perf_counter()
            got = fn(*deepcopy(case["args"]))
            r["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            r["got"] = got
            r["pass"] = _norm(got, spec["cmp"]) == _norm(case["expected"], spec["cmp"])
        except Exception:
            r["err"] = traceback.format_exc(limit=3)
        out["results"].append(r)
Path("result.json").write_text(json.dumps(out, default=repr), encoding="utf-8")
"""


def run_drill(pid: str, code: str, timeout: float = TIMEOUT_S) -> dict:
    """跑用户代码对题目全部用例。verdict: pass / fail / error / timeout。"""
    p = get_problem(pid)
    if not p:
        return {"ok": False, "error": f"未知题目：{pid}"}
    if not code.strip():
        return {"ok": False, "error": "代码是空的"}
    with tempfile.TemporaryDirectory(prefix="jl-drill-") as td:
        d = Path(td)
        (d / "sol.py").write_text(code, encoding="utf-8")
        (d / "tests.json").write_text(json.dumps(
            {"method": p["method"], "cmp": p.get("cmp", "exact"), "tests": p["tests"]}),
            encoding="utf-8")
        (d / "harn.py").write_text(_HARNESS, encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, "harn.py"], cwd=d,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": True, "verdict": "timeout", "passed": 0,
                    "total": len(p["tests"]), "cases": [],
                    "error": f"超时（>{timeout:g}s）——检查死循环或复杂度", "stdout": ""}
        res_file = d / "result.json"
        stdout = (proc.stdout or "")[-STDOUT_CAP:]
        if not res_file.exists():
            return {"ok": True, "verdict": "error", "passed": 0,
                    "total": len(p["tests"]), "cases": [],
                    "error": (proc.stderr or "判题器未产出结果")[-1500:], "stdout": stdout}
        out = json.loads(res_file.read_text(encoding="utf-8"))
        if out.get("error"):
            return {"ok": True, "verdict": "error", "passed": 0,
                    "total": len(p["tests"]), "cases": [],
                    "error": out["error"][-1500:], "stdout": stdout}
        cases = []
        for i, (case, r) in enumerate(zip(p["tests"], out["results"])):
            cases.append({"i": i + 1, "pass": r["pass"],
                          "args": json.dumps(case["args"], ensure_ascii=False),
                          "expected": json.dumps(case["expected"], ensure_ascii=False),
                          "got": json.dumps(r["got"], ensure_ascii=False, default=repr),
                          "err": (r["err"] or "")[-800:], "ms": r.get("ms", 0)})
        passed = sum(1 for c in cases if c["pass"])
        return {"ok": True, "verdict": "pass" if passed == len(cases) else "fail",
                "passed": passed, "total": len(cases), "cases": cases,
                "error": "", "stdout": stdout}
