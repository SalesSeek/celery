from __future__ import absolute_import

from contextlib import contextmanager

from kombu import Exchange
from kombu.utils.functional import maybe_promise

from celery.app import routes
from celery.exceptions import QueueNotFound
from celery.task import task
from celery.tests.case import AppCase


def Router(app, *args, **kwargs):
    return routes.Router(*args, app=app, **kwargs)


@task()
def mytask():
    pass


def E(app, queues):
    def expand(answer):
        return Router(app, [], queues).expand_destination(answer)
    return expand


@contextmanager
def _queues(app, **queues):
    prev_queues = app.conf.CELERY_QUEUES
    prev_Queues = app.amqp.queues
    app.conf.CELERY_QUEUES = queues
    app.amqp.queues = app.amqp.Queues(queues)
    try:
        yield
    finally:
        app.conf.CELERY_QUEUES = prev_queues
        app.amqp.queues = prev_Queues


class RouteCase(AppCase):

    def setup(self):
        self.a_queue = {
            'exchange': 'fooexchange',
            'exchange_type': 'fanout',
            'routing_key': 'xuzzy',
        }
        self.b_queue = {
            'exchange': 'barexchange',
            'exchange_type': 'topic',
            'routing_key': 'b.b.#',
        }
        self.d_queue = {
            'exchange': self.app.conf.CELERY_DEFAULT_EXCHANGE,
            'exchange_type': self.app.conf.CELERY_DEFAULT_EXCHANGE_TYPE,
            'routing_key': self.app.conf.CELERY_DEFAULT_ROUTING_KEY,
        }


class test_MapRoute(RouteCase):

    def test_route_for_task_expanded_route(self):
        with _queues(self.app, foo=self.a_queue, bar=self.b_queue):
            expand = E(self.app, self.app.amqp.queues)
            route = routes.MapRoute({mytask.name: {'queue': 'foo'}})
            self.assertEqual(
                expand(route.route_for_task(mytask.name))['queue'].name,
                'foo',
            )
            self.assertIsNone(route.route_for_task('celery.awesome'))

    def test_route_for_task(self):
        with _queues(self.app, foo=self.a_queue, bar=self.b_queue):
            expand = E(self.app, self.app.amqp.queues)
            route = routes.MapRoute({mytask.name: self.b_queue})
            self.assertDictContainsSubset(
                self.b_queue,
                expand(route.route_for_task(mytask.name)),
            )
            self.assertIsNone(route.route_for_task('celery.awesome'))

    def test_expand_route_not_found(self):
        expand = E(self.app, self.app.amqp.Queues(
                   self.app.conf.CELERY_QUEUES, False))
        route = routes.MapRoute({'a': {'queue': 'x'}})
        with self.assertRaises(QueueNotFound):
            expand(route.route_for_task('a'))


class test_lookup_route(RouteCase):

    def test_init_queues(self):
        router = Router(self.app, queues=None)
        self.assertDictEqual(router.queues, {})

    def test_lookup_takes_first(self):
        with _queues(self.app, foo=self.a_queue, bar=self.b_queue):
            R = routes.prepare(({mytask.name: {'queue': 'bar'}},
                                {mytask.name: {'queue': 'foo'}}))
            router = Router(self.app, R, self.app.amqp.queues)
            self.assertEqual(router.route({}, mytask.name,
                             args=[1, 2], kwargs={})['queue'].name, 'bar')

    def test_expands_queue_in_options(self):
        with _queues(self.app):
            R = routes.prepare(())
            router = Router(
                self.app, R, self.app.amqp.queues, create_missing=True,
            )
            # apply_async forwards all arguments, even exchange=None etc,
            # so need to make sure it's merged correctly.
            route = router.route(
                {'queue': 'testq',
                 'exchange': None,
                 'routing_key': None,
                 'immediate': False},
                mytask.name,
                args=[1, 2], kwargs={},
            )
            self.assertEqual(route['queue'].name, 'testq')
            self.assertEqual(route['queue'].exchange, Exchange('testq'))
            self.assertEqual(route['queue'].routing_key, 'testq')
            self.assertEqual(route['immediate'], False)

    def test_expand_destination_string(self):
        with _queues(self.app, foo=self.a_queue, bar=self.b_queue):
            x = Router(self.app, {}, self.app.amqp.queues)
            dest = x.expand_destination('foo')
            self.assertEqual(dest['queue'].name, 'foo')

    def test_lookup_paths_traversed(self):
        with _queues(self.app, foo=self.a_queue, bar=self.b_queue, **{
                self.app.conf.CELERY_DEFAULT_QUEUE: self.d_queue}):
            R = routes.prepare((
                {'celery.xaza': {'queue': 'bar'}},
                {mytask.name: {'queue': 'foo'}}
            ))
            router = Router(self.app, R, self.app.amqp.queues)
            self.assertEqual(router.route({}, mytask.name,
                             args=[1, 2], kwargs={})['queue'].name, 'foo')
            self.assertEqual(
                router.route({}, 'celery.poza')['queue'].name,
                self.app.conf.CELERY_DEFAULT_QUEUE,
            )


class test_prepare(AppCase):

    def test_prepare(self):
        from celery.datastructures import LRUCache
        o = object()
        R = [{'foo': 'bar'},
             'celery.datastructures.LRUCache', o]
        p = routes.prepare(R)
        self.assertIsInstance(p[0], routes.MapRoute)
        self.assertIsInstance(maybe_promise(p[1]), LRUCache)
        self.assertIs(p[2], o)

        self.assertEqual(routes.prepare(o), [o])

    def test_prepare_item_is_dict(self):
        R = {'foo': 'bar'}
        p = routes.prepare(R)
        self.assertIsInstance(p[0], routes.MapRoute)
