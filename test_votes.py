import vote_manager

vote_manager.reset_question()
print('Counts:', vote_manager.get_counts_and_percentages())
print('Accept user1 A ->', vote_manager.accept_vote('twitch','user1','A'))
print('Accept user2 B ->', vote_manager.accept_vote('twitch','user2','B'))
print('Counts:', vote_manager.get_counts_and_percentages())
# award points to those who answered A
voters = vote_manager.get_voters_for_letter('A')
print('Voters for A:', voters)
vote_manager.award_points(voters, points=1)
print('Leaderboard:', vote_manager.get_top_scores(10))
