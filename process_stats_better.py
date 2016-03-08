from __future__ import division
import itertools as it
from collections import OrderedDict
import json
import gzip
import math
from operator import itemgetter

bots = set(["gitter-badger", "ReadmeCritic", "invalid-email-address", "bitdeli-chef",
            "greenkeeperio-bot"])

def load_repos(data_path):
    with gzip.open(data_path + "/cached_repos.json.gz", "r") as cached_repos:
        repos = json.loads(cached_repos.read())
        return OrderedDict(sorted(repos.iteritems(), key=lambda i: -i[1]["stargazers_count"]))

def load_users(data_path):
    with gzip.open(data_path + "/cached_users.json.gz", "r") as cached_users:
        users = json.loads(cached_users.read())
        return OrderedDict(sorted(users.iteritems(), key=lambda i: -i[1]["starweight"]))

def get_crawled(crawlable):
    return {k: v for (k, v) in crawlable.iteritems() if v["crawled"] and "failed" not in v}

def is_bot(user):
    return user in bots

def remove_bots(repos, users):
    crawled_repos = get_crawled(repos)
    for (repo, repoval) in crawled_repos.iteritems():
        if "contributors" in repoval and len(repoval["contributors"]) > 0:
            for contributor in repoval["contributors"].keys():
                if is_bot(contributor):
                    repoval["total_log1p_contribs"] = repoval["total_log1p_contribs"] - repoval["contributors"][contributor]["log1p_contributions"]
                    del repoval["contributors"][contributor]
    for user in users.keys():
        if is_bot(user):
            del users[user]

def remove_uncrawled_stars(repos, users):
    crawled_repos, crawled_users = get_crawled(repos), get_crawled(users)
    for (user, userval) in crawled_users.iteritems():
        if "stars" in userval:
            for star in userval["stars"].keys():
                if star not in crawled_repos:
                    del userval["stars"][star]

def remove_no_contribs(repos):
    crawled_repos = get_crawled(repos)
    for (repo, repoval) in crawled_repos.iteritems():
        if "contributors" not in repoval or len(repoval["contributors"]) == 0:
            del repos[repo]

def calc_outbound(repos, users):
    crawled_repos, crawled_users = get_crawled(repos), get_crawled(users)
    num_repos = len(crawled_repos)
    for (repo, repoval) in crawled_repos.iteritems():
        repoval["shadow_starlist"] = {}
        if "contributors" in repoval and len(repoval["contributors"]) > 0:
            starsum = 0
            for (contributor, contribval) in repoval["contributors"].iteritems():
                if "contrib_list" not in users[contributor]:
                    users[contributor]["contrib_list"] = []
                users[contributor]["contrib_list"].append(repo)
                if (not is_bot(contributor)) and contributor in crawled_users and "stars" in crawled_users[contributor]:
                    starcount = len([s for s in crawled_users[contributor]["stars"].keys() if s in crawled_repos])
                    if starcount > 0:
                        starsum += contribval["log1p_contributions"]
                        for star in crawled_users[contributor]["stars"].keys():
                            if star in crawled_repos:
                                if star not in repoval["shadow_starlist"]:
                                    repoval["shadow_starlist"][star] = 0
                                repoval["shadow_starlist"][star] = repoval["shadow_starlist"][star] + (contribval["log1p_contributions"] / starcount)
            for star in repoval["shadow_starlist"].keys():
                repoval["shadow_starlist"][star] = repoval["shadow_starlist"][star] / starsum
        if len(repoval["shadow_starlist"]) == 0:
            repoval["shadow_starlist"] = {r: 1.0/num_repos for r in crawled_repos.keys()}
    for (repo, repoval) in crawled_repos.iteritems():
        repoval["contriblist"] = {}
        if "contributors" in repoval and len(repoval["contributors"]) > 0:
            contribsum = 0
            for (contributor, contribval) in repoval["contributors"].iteritems():
                if (not is_bot(contributor)):
                    contribcount = len(users[contributor]["contrib_list"])
                    contribsum += contribval["log1p_contributions"]
                    for contributed_to in users[contributor]["contrib_list"]:
                        if contributed_to not in repoval["contriblist"]:
                            repoval["contriblist"][contributed_to] = 0
                        repoval["contriblist"][contributed_to] = repoval["contriblist"][contributed_to] + (contribval["log1p_contributions"] / contribcount)
            for contributed_to in repoval["contriblist"].keys():
                repoval["contriblist"][contributed_to] = repoval["contriblist"][contributed_to] / contribsum
        if len(repoval["contriblist"]) == 0:
            repoval["contriblist"] = {r: 1.0/num_repos for r in crawled_repos.keys()}

def calc_inbound(repos, contrib_prob = 0.333333):
    crawled_repos = get_crawled(repos)
    res = {}
    for (src, srcval) in crawled_repos.iteritems():
        for (dst, dstval) in srcval["contriblist"].iteritems():
            if dst not in res:
                res[dst] = {}
            if src not in res[dst]:
                res[dst][src] = 0
            res[dst][src] = res[dst][src] + contrib_prob * dstval
        for (dst, dstval) in srcval["shadow_starlist"].iteritems():
            if dst not in res:
                res[dst] = {}
            if src not in res[dst]:
                res[dst][src] = 0
            res[dst][src] = res[dst][src] + (1 - contrib_prob) * dstval
    return res

def calc_graph(repos, users):
    crawled_repos, crawled_users = get_crawled(repos), get_crawled(users)

    links = {}
    contrib_counts = {}

    # Create links from repo to contributors
    for (repo, repoval) in crawled_repos.iteritems():
        if "contributors" in repoval and len(repoval["contributors"]) > 0:
            total_log1p_contribs = repoval["total_log1p_contribs"]
            for (contributor, contribval) in repoval["contributors"].iteritems():
                if not is_bot(contributor):
                    if contributor in links:
                        links[contributor][1][repo] = contribval["log1p_contributions"] / total_log1p_contribs
                    else:
                        links[contributor] = ("user", {repo: contribval["log1p_contributions"] / total_log1p_contribs})

                    if contributor in contrib_counts:
                        contrib_counts[contributor] = contrib_counts[contributor] + 1
                    else:
                        contrib_counts[contributor] = 1

    # Create links from contributors to repo
    for (repo, repoval) in crawled_repos.iteritems():
        if "contributors" in repoval and len(repoval["contributors"]) > 0:
            links[repo] = ("repo", {contributor: 1.0/contrib_counts[contributor] \
                                    for contributor in repoval["contributors"].keys()\
                                    if not is_bot(contributor)}, {})

    # Create links from starrers to repo
    user_starcounts = {linker: len([s for s in crawled_users[linker]["stars"].keys() if s in links]) for linker in crawled_users.keys()}
    for (user, userval) in crawled_users.iteritems():
        if not is_bot(user):
            if "stars" in userval:
                starcount = len([s for s in userval["stars"].keys() if s in crawled_repos])
                for (repo, repoval) in userval["stars"].iteritems():
                    if repo in links:
                        links[repo][2][user] = 1.0 / starcount

    return links

def calc_gitrank_graph(links, iters=25, damping=0.85, contrib_prob=0.33333):
    num_nodes = len(links)
    users = [key for (key, val) in links.iteritems() if val[0] == "user"]
    repos = [key for (key, val) in links.iteritems() if val[0] == "repo"]
    ranks = {key: 1.0/num_nodes for key in links.keys()}

    for i in xrange(iters):
        print "round {0}".format(i+1)
        newranks = {}
        for user in users:
            # only get to a user from a repo
            newranks[user] = (1.0 - damping) / num_nodes \
                            + damping * sum([ranks[repo]*weight for (repo, weight) in links[user][1].iteritems()])

        for repo in repos:
            # two sums
            newranks[repo] = (1.0 - damping) / num_nodes \
                            + damping * contrib_prob * sum([ranks[user]*weight for (user, weight) in links[repo][1].iteritems()]) \
                            + damping * (1 - contrib_prob) * sum([ranks[user]*weight for (user, weight) in links[repo][2].iteritems()])

        ranks = newranks

    return OrderedDict(sorted([(repo, ranks[repo]) for repo in repos], key=lambda x: -x[1])), \
            OrderedDict(sorted([(user,
                                (ranks[user],
                                 OrderedDict(sorted([(repo, damping * ranks[repo] * weight) \
                                                    for (repo, weight) in links[user][1].iteritems()], key=lambda x: -x[1])))) \
                                for user in users], key=lambda x: -x[1][0]))

def calc_gitrank_better(r2r, iters=25, damping=0.85):
    num_nodes = len(r2r)
    ranks = {key: 1.0/num_nodes for key in r2r.keys()}
    for i in xrange(iters):
        print "round {0}".format(i+1)
        newranks = {}
        for (dst, dstval) in r2r.iteritems():
            newranks[dst] = (1.0 - damping) / num_nodes + \
                            damping * sum([ranks[src]*weight for (src, weight) in dstval.iteritems()])
        ranks = newranks
    return OrderedDict(sorted(ranks.iteritems(), key=lambda x: x[1], reverse=True))

def repo_to_repo_links(links, contrib_prob=0.33333):
    repos = [key for (key, val) in links.iteritems() if val[0] == "repo"]
    repo_to_repo = {linked_to: {linker: 0 for linker in repos} for linked_to in repos}
    ig1 = itemgetter(1)
    for linked_to in repos:
        for (user, userweight) in links[linked_to][1].iteritems():
            for (linker, linkerweight) in links[user][1].iteritems():
                repo_to_repo[linked_to][linker] = repo_to_repo[linked_to][linker] \
                                                + contrib_prob * linkerweight * userweight
        for (user, userweight) in links[linked_to][2].iteritems():
            for (linker, linkerweight) in links[user][1].iteritems():
                repo_to_repo[linked_to][linker] = repo_to_repo[linked_to][linker] \
                                                + (1-contrib_prob) * linkerweight * userweight
        repo_to_repo[linked_to] = OrderedDict([x for x in sorted(repo_to_repo[linked_to].iteritems(), key=ig1, reverse=True) if x[1] >= 0.001])

    linkedrepos = sorted([(r1, r2, repo_to_repo[r1][r2], repo_to_repo[r2][r1]) \
                           for r1 in repos for r2 in repos \
                           if r1 in repo_to_repo[r2] and r2 in repo_to_repo[r1] and r1 < r2],
                          key = lambda x: -x[2]-x[3])

    return repo_to_repo, linkedrepos

def outbound_r2r(r2r):
    res, ig1 = {}, itemgetter(1)
    for r1 in r2r.keys():
        for r2 in r2r[r1].keys():
            if r2 not in res:
                res[r2] = {}
            res[r2][r1] = r2r[r1][r2]
    for r2 in res.keys():
        res[r2] = OrderedDict([x for x in sorted(res[r2].iteritems(), key=ig1, reverse=True)])
    return res

def calc_similarities(r2r, initial_pref=0, num_iters=10, damping=0.95, pruning=0.0002):
    repos = r2r.keys()
    pruned_r2r = {r1: {r2: val for (r2, val) in d.iteritems() if val > pruning} for (r1, d) in r2r.iteritems()}
    sim = {}
    for (exemplar, points) in pruned_r2r.iteritems():
        for (point, weight) in points.iteritems():
            if point not in sim:
                sim[point] = {}
            sim[point][exemplar] = weight * (1 if point != exemplar else initial_pref)

    avail = {exemplar: {point: 0 \
            for point in pruned_r2r[exemplar].keys()} for exemplar in repos}

    oldresp, oldavail, damp = None, None, 1
    for i in xrange(num_iters):
        print "round {0}".format(i+1)
        # todo: fix damping
        resp = {}
        for point in sim.keys():
            avail_plus_sim = [(cand, avail[cand][point] + sim[point][cand]) \
                                for cand in sim[point].keys()]
            best, second_best = (None, 0), (None, 0)
            for (cand, a_plus_s) in avail_plus_sim:
                if a_plus_s > best[1]:
                    second_best = best
                    best = (cand, a_plus_s)
                elif a_plus_s > second_best[1]:
                    second_best = (cand, a_plus_s)
                else:
                    pass

            resp[point] = {exemplar: \
                            (oldresp[point][exemplar]*(1-damp) if oldresp != None else 0) + \
                            (damp if oldresp != None else 1) * \
                            (sim[point][exemplar] - \
                            (best[1] if best[0] != exemplar else second_best[1]))\
                            for exemplar in sim[point].keys()}

        avail = {}
        for exemplar in repos:
            positive_resps = sum([max(0, resp[otherpoint][exemplar]) for otherpoint in pruned_r2r[exemplar].keys()])
            avail[exemplar] = {point: \
                                (oldavail[exemplar][point]*(1-damp) if oldavail != None else 0) + \
                                (damp if oldavail != None else 1) * \
                (min(0, resp[exemplar][exemplar] + positive_resps - max(0, resp[point][exemplar]) - max(0, resp[exemplar][exemplar])) \
                    if point != exemplar else \
                (positive_resps - max(0, resp[exemplar][exemplar]))) \
                for point in pruned_r2r[exemplar].keys()}

        oldresp, oldavail, damp = resp, avail, damp * damping

    return resp, avail

def gen_exemplars(resp, avail):
    exemplars = {point: max(resp[point].keys(), key=lambda exemplar: resp[point][exemplar] + avail[exemplar][point]) \
                for point in resp.keys()}
    children = {}
    for (point, exemplar) in exemplars.items():
        if exemplar not in children:
            children[exemplar] = []
        children[exemplar].append(point)

    return exemplars, children

def collapseTreeNode(node):
    if "children" in node:
        for child in node["children"]:
            collapseTreeNode(child)
        if len(node["children"]) == 1:
            if node["name"] != node["children"][0]["name"]:
                raise ValueError("Expected " + node["name"] + " to equal " + node["children"][0]["name"])
            elif "children" not in node["children"][0]:
                del node["children"]
            else:
                node["children"] = node["children"][0]["children"]

def recluster(repos, prev_r2r, prev_ch, num_iters, damping=0.95):
    prev_exemplars = [x for x in prev_ch if x in prev_ch[x]]
    next_r2r = {r1: {r2: prev_r2r[r1][r2] for r2 in prev_r2r[r1].keys() if r2 in prev_exemplars} for r1 in prev_r2r.keys() if r1 in prev_exemplars}
    resp, avail = calc_similarities(next_r2r, repos, 0, num_iters, damping)
    next_ex, next_ch = gen_exemplars(resp, avail)
    return next_r2r, next_ch

def eco_r2r(r2r, gitrank, ch, r1, r2):
    return sum([gitrank[ch2] * r2r[ch1][ch2] for ch1 in ch[r1] if ch1 in r2r for ch2 in r2r[ch1].keys() if ch2 in ch[r2]]) \
            / sum([gitrank[ch2] for ch2 in ch[r2]])

def cluster_r2r(r2r, gitrank, ch):
    exemplars = [x for x in ch if x in ch[x]]
    clustered_gitrank = OrderedDict(sorted([(exemplar, sum([gitrank[child] for child in ch[exemplar]])) for exemplar in exemplars],
                                            key=lambda x: x[1], reverse=True))
    clustered_r2r = {dst: \
                        {src: \
                            sum([r2r[child_dst][child_src]*gitrank[child_src] for child_dst in ch[dst] for child_src in ch[src] if child_src in r2r[child_dst]])/clustered_gitrank[src] \
                        for src in exemplars} \
                    for dst in exemplars}
    return clustered_r2r, clustered_gitrank

def recluster_better(prev_r2r, prev_gitrank, prev_ch, num_iters, initial_pref=0, damping=0.95):
    # Not better yet
    next_r2r, next_gitrank = cluster_r2r(prev_r2r, prev_gitrank, prev_ch)
    resp, avail = calc_similarities(next_r2r, repos, 0, num_iters, damping)
    next_ex, next_ch = gen_exemplars(resp, avail)
    return next_r2r, next_ch

def main():
    data_path = "./downloaded_data"
    repos, users = load_repos(data_path), load_users(data_path)
    remove_bots(repos, users)
    remove_uncrawled_stars(repos, users)
    remove_no_contribs(repos)
    calc_outbound(repos, users)
    r2r = calc_inbound(repos)
    resp, avail = calc_similarities(r2r, 0, 20)
    ex, ch = gen_exemplars(resp, avail)

    r2r_2, ch2 = recluster(repos, r2r, ch, 30, 0.97)
    r2r_3, ch3 = recluster(repos, r2r_2, ch2, 50, 0.99)
    r2r_4, ch4 = recluster(repos, r2r_3, ch3, 100, 0.99)

    d3_gitmap = {"name": "github", "children": [ \
                    {"name": root, "children": [ \
                        {"name": greatgrandpa, "children": [ \
                            {"name": grandpa, "children": [ \
                                {"name": dad, "children": \
                                    [{"name": child} \
                                    for child in sorted(ch[dad])]} \
                                for dad in sorted(ch2[grandpa])]} \
                            for grandpa in sorted(ch3[greatgrandpa])]} \
                        for greatgrandpa in sorted(ch4[root])]} \
                    for root in sorted(ch4.keys())]}
    collapseTreeNode(d3_gitmap)
    full_gitmap = {"tree": d3_gitmap, "links": [(r1, r2) for (r1, r2, r3, r4) in linkedrepos]}
    with open("gitmap.json", "w") as f:
        f.write(json.dumps(full_gitmap)) #, indent=2))

if __name__ == "__main__":
    main()