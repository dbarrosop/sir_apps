Summary
-------

This application will use SIR to optimize the FIB of an Arista switch. For a given period of time it's going to get the TopN prefixes in terms of data transferred and build prefix lists with those prefixes. Those prefix-lists can be used in a route-map to control with SRD which prefixes you want to install in the FIB.

Usage
-----

From the EOS bash:

    sudo ip netns exec ns-mgmtVRF /mnt/flash/fib_optimizer/fib_optimizer.py https://127.0.0.1/sir

 > Replace **ns-mgmtVRF** with *default* if you are not using any management vrf or with *ns-YOUR_MANAGEMENT_VRF_NAME* if you are using a different vrf.

That will create two files:

* */tmp/fib_optimizer_lpm_v4* - LPM prefixes
* */tmp/fib_optimizer_lem_v4* - LEM prefixes

More on LPM/LEM prefixes later. To use them you will need the following configuration (adapt for your particular setup):

    ip prefix-list fib_optimizer_manual_prefixes
        permit 0.0.0.0/0      # We always want the default route
        permit 192.168.1.0/24 # We also want to allow always our internal networks

    ip prefix-list fib_optimizer_lem file:/tmp/fib_optimizer_lem
    ip prefix-list fib_optimizer_lpm file:/tmp/fib_optimizer_lpm

    route-map SRD permit 10
        match ip address prefix-list fib_optimizer_manual_prefixes
    route-map SRD permit 20
        match ip address prefix-list fib_optimizer_lem
    route-map SRD permit 30
        match ip address prefix-list fib_optimizer_lpm
    route-map SRD deny 100

    router bgp 65000
       bgp route install-map SRD


LPM vs LEM
----------

When you are matching routes you can do it in two ways:

* LPM (Longest Prefix Match) - This means that this is the best match for your route using the prefix length as well. This is how you usually match a route that you have in your routing table.
* LEM (Longest Exact Match) - If you are matching a /32 you are doing a an exact match. In this case you don't need to look up the prefix-length of the prefix because you are only matching using the network. This has the advantage that you don't need to store the prefix-lenght because that information is not needed.

In switches the LPM table is usually quite limited and used only to store prefixes with different prefix-lengts whereas the LEM table is very large and is used to store a variety of things:

* /32 prefixes
* MAC addresses
* others...

However, Arista has a nifty trick where you can instruct the system to store /24 prefixes in the LEM table. That can boost the amount of routes you can install in your system. For example, in my lab, using an Arista 7280 I experienced the following improvements:

* Without the LEM trick: ~16.000-24.000 prefixes
* With the LEM trick: ~220.000 prefixes (200k /24s + 20k non-/24s)

I recommend you to contact your SE before enabling this trick. However, you can enable it with the following command:

    ip hardware fib optimize prefix-length 32 24

Refreshing the Prefix Lists
--------------------------

You can easily refresh the prefix lists by running the tool automatically every hour. EOS can easily do that with the "schedule" command. For example:

    peer00.lab(config)#schedule fib_optimizer at 17:05:00 interval 60 max-log-files 48 command bash sudo ip netns exec ns-mgmtVRF /mnt/flash/fib_optimizer/fib_optimizer.py https://127.0.0.1/sir

Required variables
------------------

This application needs the following variables inside the SIR agent:

* lem_prefixes - Prefix length you want to install in the LEM table. Today EOS only supports the prefix-length "24".
* max_lem_prefixes - How many LEM prefixes you want. I recommend 20000 for the Arista 7280. You can boost this number up to 65500 if you want.
* max_lpm_prefixes - How many LPM prefixes you want. I recommend 16000 for the Arista 7280.
* path - Where do you want to store the prefix lists. Recommended '/tmp'.
* age - How many hours you want to go back to compute the TopN prefixes. For example, if you set 168 you will compute the TopN prefixes for the last 7 days.
* purge_older_than - BGP data and flows that are older than 'purge_older_than' (in hours) will be purged. Recommended; age*2. If set to 0, no data is purged ever.

You can set the variables from the python shell doing the following:

    from pySIR.pySIR import pySIR
    import json

    base_url = 'https://route.lab/sir'
    configuration = {
        'lem_prefixes': '24',
        'max_lem_prefixes': 20000,
        'max_lpm_prefixes': 16000,
        'path': '/tmp/',
        'age': 168,
        'purge_older_than': 336,
    }
    sir = pySIR(base_url, verify_ssl=False)
    sir.delete_variables_by_category_and_name(name='fib_optimizer', category='apps')

    sir.post_variables(
        name = 'fib_optimizer',
        content = json.dumps(configuration),
        category = 'apps',
    )

Safeties
--------

To avoid issues as much as possible there are three safeties:

 1. First of all, it is recommended you use something like the prefix list *fib_optimizer_manual_prefixes* in the example to install some default prefixes that you will always want. Those prefixes can be your default route, your internal networks...
 1. The script will automatically stop if:
  1. There has not been new data for the last 48 hours.
  1. The new prefix length is 25% smaller than the previous one.
