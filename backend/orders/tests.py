import json
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Customer, Order, OrderItem, Wallet, WalletTransaction


class WalletPaymentFlowTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='مشتری آزمایشی',
            phone='09123456789',
        )
        self.wallet = Wallet.objects.create(
            customer=self.customer,
            balance=Decimal('0'),
        )
        self.order = Order.objects.create(
            customer=self.customer,
            total_price=Decimal('25000'),
        )
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='wallet-admin',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )

    def customer_client(self):
        client = Client()
        session = client.session
        session['customer_id'] = self.customer.id
        session['customer_logged_in'] = True
        session.save()
        return client

    def test_successful_wallet_payment_returns_to_the_same_invoice(self):
        self.wallet.balance = Decimal('60000')
        self.wallet.save()

        response = self.customer_client().post(
            reverse('wallet_pay_order', args=[self.order.id])
        )

        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.order.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.wallet.balance, Decimal('35000'))
        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                order=self.order,
                transaction_type='debit',
                amount=Decimal('25000'),
            ).exists()
        )

    def test_insufficient_wallet_balance_still_returns_to_the_invoice(self):
        self.wallet.balance = Decimal('10000')
        self.wallet.save()

        response = self.customer_client().post(
            reverse('wallet_pay_order', args=[self.order.id])
        )

        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    def test_admin_manual_top_up_accepts_persian_grouped_amount_and_can_pay_invoice(self):
        admin_client = Client()
        admin_client.force_login(self.staff)
        response = admin_client.post(
            reverse('panel_customer_update', args=[self.customer.id]),
            {
                'name': self.customer.name,
                'phone': self.customer.phone,
                'password': '',
                'wallet_balance': '۱٬۰۰۰٬۰۰۰',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1000000'))
        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type='credit',
                amount=Decimal('1000000'),
                description='شارژ دستی توسط مدیریت',
            ).exists()
        )

        response = self.customer_client().post(
            reverse('wallet_pay_order', args=[self.order.id])
        )
        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.wallet.refresh_from_db()
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.wallet.balance, Decimal('975000'))


def login_customer(client, customer):
    session = client.session
    session['customer_id'] = customer.id
    session['customer_logged_in'] = True
    session.save()
    return client


class ReceiptAccessTests(TestCase):
    def setUp(self):
        self.owner = Customer.objects.create(name='صاحب سفارش', phone='09120000011')
        self.other = Customer.objects.create(name='مشتری دیگر', phone='09120000012')
        self.order = Order.objects.create(customer=self.owner, total_price=Decimal('10000'))
        self.url = reverse('print_receipt', args=[self.order.id])

    def test_guest_is_sent_to_login(self):
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('customer_login'), response['Location'])
        self.assertNotContains(Client().get(self.url, follow=True), self.owner.phone)

    def test_other_customer_gets_404(self):
        response = login_customer(Client(), self.other).get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_owner_and_staff_can_view(self):
        response = login_customer(Client(), self.owner).get(self.url)
        self.assertContains(response, '۰۹۱۲۰۰۰۰۰۱۱')
        self.assertNotContains(response, f'phone={self.owner.phone}')
        staff = get_user_model().objects.create_user('receipt-staff', password='x', is_staff=True)
        client = Client()
        client.force_login(staff)
        self.assertContains(client.get(self.url), self.owner.name)


class WalletVerifyTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='شارژ کننده', phone='09120000013')
        self.wallet = Wallet.objects.create(customer=self.customer, balance=Decimal('0'))
        self.tx = WalletTransaction.objects.create(
            wallet=self.wallet, transaction_type='credit', amount=Decimal('20000'), authority='A-test-1',
        )
        self.client = login_customer(Client(), self.customer)
        self.url = reverse('verify_wallet') + f'?transaction_id={self.tx.id}&Authority=A-test-1&Status=OK'

    def gateway(self, code=100):
        from unittest import mock
        response = mock.Mock(status_code=200, content=b'1')
        response.json.return_value = {'data': {'code': code, 'ref_id': 12345}}
        return mock.patch('orders.views.requests.post', return_value=response)

    def test_cancelled_payment_adds_nothing(self):
        url = reverse('verify_wallet') + f'?transaction_id={self.tx.id}&Authority=A-test-1&Status=NOK'
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'پرداخت لغو شد')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 0)

    def test_repeated_callback_credits_once(self):
        with self.gateway(100):
            self.client.get(self.url)
        with self.gateway(101):
            self.client.get(self.url)
            self.client.get(self.url)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('20000'))

    def test_claim_is_single_use(self):
        from .views import credit_wallet_transaction
        self.assertTrue(credit_wallet_transaction(self.tx, '1'))
        self.assertFalse(credit_wallet_transaction(self.tx, '1'))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('20000'))

    def test_other_customer_cannot_verify(self):
        other = login_customer(Client(), Customer.objects.create(name='دیگری', phone='09120000014'))
        with self.gateway(100):
            other.get(self.url)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 0)


class CourierLocationTests(TestCase):
    def test_clean_courier_location(self):
        from .views import clean_courier_location
        ok, error = clean_courier_location('۳۵.۷', '51.3', '۱۲۳۴۵ ۶۷۸۹۰')
        self.assertIsNone(error)
        self.assertEqual(ok, ('35.700000', '51.300000', '1234567890'))
        for lat, lng in [('nan', '51'), ('inf', '51'), ('999', '51'), ('35', '-999'), ('', ''), ('abc', '51')]:
            self.assertIsNotNone(clean_courier_location(lat, lng, '1234567890')[1], (lat, lng))
        for postal in ['123456789', '12345678901', 'abcdefghij', '', '0000000000', '۱۱۱۱۱۱۱۱۱۱']:
            self.assertIsNotNone(clean_courier_location('35.7', '51.3', postal)[1], postal)


@override_settings(MAPIR_API_KEY='test-key', MAPIR_POSTAL_URL='https://map.example/postal/{code}')
class PostalLookupTests(TestCase):
    """map.ir is mocked: these check how each kind of answer is read, not the real service."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def answer(self, status=200, data=None, text=''):
        from unittest import mock
        response = mock.Mock(status_code=status, text=text or json.dumps(data))
        response.json.return_value = data
        if data is None:
            response.json.side_effect = ValueError
        return mock.patch('orders.postal.requests.get', return_value=response)

    def test_found_answer_gives_point_and_address(self):
        from .postal import lookup_postal_code
        data = {'value': [{'geometry': {'coordinates': [51.29, 35.72]}, 'address': 'تهران، خیابان بهار'}]}
        with self.answer(data=data) as get:
            result = lookup_postal_code('۱۳۴۵۶۷۸۹۱۰')
        self.assertEqual(result, {'status': 'found', 'lat': 35.72, 'lng': 51.29, 'address': 'تهران، خیابان بهار'})
        self.assertEqual(get.call_args.args[0], 'https://map.example/postal/1345678910')
        self.assertEqual(get.call_args.kwargs['headers']['x-api-key'], 'test-key')

    def test_found_answers_are_cached(self):
        from .postal import lookup_postal_code
        with self.answer(data={'lat': 35.7, 'lng': 51.3}) as get:
            lookup_postal_code('1345678910')
            lookup_postal_code('1345678910')
        self.assertEqual(get.call_count, 1)

    def test_missing_code_is_not_found(self):
        from .postal import lookup_postal_code
        with self.answer(status=404, data={}):
            self.assertEqual(lookup_postal_code('1345678910')['status'], 'not_found')
        with self.answer(data={'value': []}):
            self.assertEqual(lookup_postal_code('1345678911')['status'], 'not_found')

    def test_unclear_or_failed_answers_never_block(self):
        from .postal import lookup_postal_code
        with self.answer(data={'something': 'else'}):
            self.assertEqual(lookup_postal_code('1345678910')['status'], 'unavailable')
        with self.answer(status=500, data={}):
            self.assertEqual(lookup_postal_code('1345678912')['status'], 'unavailable')
        with self.answer(data=None, text='<html>'):
            self.assertEqual(lookup_postal_code('1345678913')['status'], 'unavailable')
        with self.answer(data={'lat': 48.8, 'lng': 2.3}):  # outside Iran: not understood
            self.assertEqual(lookup_postal_code('1345678914')['status'], 'unavailable')

    @override_settings(MAPIR_API_KEY='', MAPIR_POSTAL_URL='')
    def test_without_settings_nothing_is_called(self):
        from .postal import lookup_postal_code
        with self.answer(data={}) as get:
            self.assertEqual(lookup_postal_code('1345678910')['status'], 'unavailable')
        get.assert_not_called()

    def test_courier_location_rejects_unknown_postal_code(self):
        from .views import clean_courier_location
        with self.answer(status=404, data={}):
            location, error = clean_courier_location('35.7', '51.3', '1345678910')
        self.assertIsNone(location)
        self.assertIn('پیدا نشد', error)

    def test_lookup_endpoint_needs_login_and_reports_result(self):
        url = reverse('postal_lookup')
        self.assertEqual(self.client.get(url, {'code': '1345678910'}).status_code, 403)
        customer = Customer.objects.create(name='مشتری', phone='09120000001')
        login_customer(self.client, customer)
        self.assertEqual(self.client.get(url, {'code': '123'}).json()['status'], 'invalid')
        with self.answer(data={'lat': 35.7, 'lng': 51.3, 'address': 'تهران'}):
            body = self.client.get(url, {'code': '۱۳۴۵۶۷۸۹۱۰'}).json()
        self.assertEqual(body['status'], 'found')
        self.assertEqual(body['address'], 'تهران')


class AccountInsightsTests(TestCase):
    def setUp(self):
        from .models import OrderItem
        self.customer = Customer.objects.create(name='مشتری آمار', phone='09120000099')
        first = Order.objects.create(customer=self.customer, courier_requested=True)
        OrderItem.objects.create(order=first, item_name='کت مردانه (خشکشویی + اتو)', quantity=2, price=Decimal('100000'))
        OrderItem.objects.create(order=first, item_name='شلوار مردانه (فقط اتو)', quantity=1, price=Decimal('50000'))
        second = Order.objects.create(customer=self.customer, status='delivered')
        OrderItem.objects.create(order=second, item_name='کت مردانه (خشکشویی + اتو)', quantity=1, price=Decimal('100000'))

    def test_counts_top_items_and_facts(self):
        from .insights import customer_insights, split_item_name
        self.assertEqual(split_item_name('کت و شلوار مردانه (خشکشویی + اتو)'), ('کت و شلوار مردانه', 'خشکشویی + اتو'))
        s = customer_insights(self.customer)
        self.assertEqual((s['orders_count'], s['pieces'], s['active']), (2, 4, 1))
        self.assertEqual(s['top_items'][0]['name'], 'کت مردانه')
        self.assertEqual(s['top_items'][0]['count'], 3)
        self.assertEqual((s['dry_pieces'], s['iron_pieces'], s['dry_share']), (3, 1, 75))
        self.assertEqual(s['courier_orders'], 1)
        self.assertIn('کت مردانه', s['facts'][0]['text'])

    def test_account_page_shows_dashboard(self):
        login_customer(self.client, self.customer)
        html = self.client.get(reverse('account')).content.decode()
        self.assertIn('بیشتر چه چیزهایی سفارش داده‌اید؟', html)
        self.assertIn('کت مردانه', html)
        empty = Customer.objects.create(name='تازه', phone='09120000098')
        login_customer(self.client, empty)
        self.assertIn('هنوز سفارشی ثبت نکرده‌اید', self.client.get(reverse('account')).content.decode())


class DeliveryCourierRequestTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='پیک', phone='09120000015')
        self.order = Order.objects.create(customer=self.customer, status='ready', total_price=Decimal('100000'))
        self.client = login_customer(Client(), self.customer)

    def post(self, payload, client=None):
        return (client or self.client).post(reverse('request_courier'), json.dumps(payload), content_type='application/json')

    def test_request_then_edit_until_dispatched(self):
        payload = {'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '۱۲۳۴۵۶۷۸۹۰'}
        self.assertEqual(self.post(payload).json()['status'], 'success')
        self.order.refresh_from_db()
        self.assertTrue(self.order.delivery_courier_requested)
        self.assertEqual(self.order.delivery_postal_code, '1234567890')
        payload['postal'] = '1357924680'
        self.assertEqual(self.post(payload).json()['message'], 'آدرس ارسال به‌روز شد.')
        self.order.delivery_courier_dispatched = True
        self.order.save()
        self.assertEqual(self.post(payload).status_code, 400)

    def test_errors_are_persian(self):
        other = login_customer(Client(), Customer.objects.create(name='دیگری', phone='09120000016'))
        for response in [
            self.post({'order_id': 'abc', 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'}),
            self.post({'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'}, other),
            self.post([]),
        ]:
            message = response.json()['message']
            self.assertTrue(re.search('[آ-ی]', message), message)
            self.assertNotIn('matches the given query', message)
        self.order.status = 'delivered'
        self.order.save()
        response = self.post({'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'})
        self.assertEqual(response.json()['message'], 'این سفارش قبلاً تحویل داده شده است.')

    def test_tracking_page_hides_method_chooser_after_request(self):
        page = self.client.get(reverse('home'), {'order_id': self.order.id}).content.decode()
        self.assertIn('نحوه دریافت لباس را انتخاب کنید', page)
        self.post({'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'})
        page = self.client.get(reverse('home'), {'order_id': self.order.id}).content.decode()
        self.assertNotIn('نحوه دریافت لباس را انتخاب کنید', page)
        self.assertIn('ویرایش آدرس ارسال', page)


class PlaceOrderTests(TestCase):
    def setUp(self):
        from .models import PriceCategory, PriceItem
        self.customer = Customer.objects.create(name='سفارش‌دهنده', phone='09120000017')
        men = PriceCategory.objects.create(name='مردانه')
        self.shirt = PriceItem.objects.create(category=men, name='پیراهن', dry_clean_price='220000', iron_only_price='160000')
        self.trousers = PriceItem.objects.create(category=men, name='شلوار', dry_clean_price='220,000', iron_only_price='160000')
        self.coat = PriceItem.objects.create(category=men, name='کاپشن', dry_clean_price='', iron_only_price=None)
        self.client = login_customer(Client(), self.customer)

    def post(self, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload)
        return self.client.post(reverse('place_order'), body, content_type='application/json')

    def test_normal_order_totals_and_labels(self):
        response = self.post({'items': [
            {'line_id': self.shirt.id, 'quantity': 2, 'description': 'یقه لک دارد'},
            {'line_id': self.trousers.id, 'quantity': 1, 'iron_only': True},
        ]})
        data = response.json()
        self.assertEqual(data['status'], 'success')
        order = Order.objects.get(id=data['order_id'])
        self.assertEqual(order.total_price, Decimal('600000'))
        self.assertEqual(data['total'], 600000)
        self.assertEqual(order.tax_amount, 0)
        names = sorted(order.orderitem_set.values_list('item_name', flat=True))
        self.assertEqual(names, ['شلوار مردانه (فقط اتو)', 'پیراهن مردانه (خشکشویی + اتو)'])

    def test_bad_input_never_leaves_an_order(self):
        bad_payloads = [{'items': []}, {'items': 'x'}] + [
            {'items': [{'line_id': self.shirt.id, 'quantity': q}]}
            for q in (0, -5, '1.5', 2.7, 99999, 10 ** 20, 'abc', None, True)
        ]
        bad_payloads += [
            {'items': [{'line_id': 999999, 'quantity': 1}]},
            {'items': [{'line_id': self.coat.id, 'quantity': 1, 'iron_only': True}]},
            {'items': [self.shirt.id]},
            {'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'delivery_method': 'courier', 'lat': 'nan', 'lng': '51', 'postal': '1234567890'},
        ]
        for payload in bad_payloads:
            response = self.post(payload)
            self.assertEqual(response.json()['status'], 'error', payload)
            self.assertTrue(re.search('[آ-ی]', response.json()['message']), payload)
        for raw in ['[]', '{bad', 'null']:
            self.assertEqual(self.post(None, raw=raw).json()['status'], 'error')
        self.assertEqual(Order.objects.count(), 0)

    def test_changed_price_is_rejected(self):
        response = self.post({'items': [{'line_id': self.shirt.id, 'quantity': 1, 'price_numeric': 200000}]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Order.objects.count(), 0)

    def test_unpriced_item_is_allowed_at_zero(self):
        data = self.post({'items': [{'line_id': self.coat.id, 'quantity': 1, 'price_numeric': None}]}).json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['total'], 0)

    def test_courier_order_saves_normalized_location_and_address(self):
        data = self.post({
            'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'delivery_method': 'courier',
            'lat': '35.72', 'lng': '51.29', 'postal': '۱۲۳۴۵۶۷۸۹۰', 'address': 'تهران، پلاک ۱', 'save_address': True,
        }).json()
        order = Order.objects.get(id=data['order_id'])
        self.assertEqual((order.status, order.postal_code), ('collecting', '1234567890'))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.address_postal_code, '1234567890')
        self.assertTrue(self.customer.has_saved_address)

    def test_wallet_payment_on_order(self):
        Wallet.objects.create(customer=self.customer, balance=Decimal('300000'))
        data = self.post({'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'use_wallet': True}).json()
        self.assertTrue(data['paid_by_wallet'])
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('80000'))
        data = self.post({'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'use_wallet': True}).json()
        self.assertTrue(data['wallet_insufficient'])
        self.assertFalse(Order.objects.get(id=data['order_id']).is_paid)
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('80000'))
        self.assertEqual(WalletTransaction.objects.filter(transaction_type='debit').count(), 1)

    def test_no_tax_on_new_orders_but_old_paid_receipts_keep_it(self):
        data = self.post({'items': [{'line_id': self.shirt.id, 'quantity': 1}]}).json()
        page = self.client.get(reverse('home'), {'order_id': data['order_id']}).content.decode()
        self.assertNotIn('مالیات (۱۰٪)', page)
        # Paid back when the 10% was still added: the receipt still explains the amount that was paid.
        old = Order.objects.create(customer=self.customer, is_paid=True)
        OrderItem.objects.create(order=old, item_name='کت', quantity=1, price=100000)
        Order.objects.filter(pk=old.pk).update(total_price=110000)
        old.refresh_from_db()
        self.assertEqual(old.tax_amount, 10000)
        receipt = self.client.get(reverse('print_receipt', args=[old.id])).content.decode()
        self.assertIn('مالیات (۱۰٪)', receipt)


class PricePendingPaymentTests(TestCase):
    """Items priced after inspection: no payment until the order is ready and fully priced."""

    def setUp(self):
        from .models import PriceCategory, PriceItem
        self.customer = Customer.objects.create(name='قیمت بعدی', phone='09120000031')
        men = PriceCategory.objects.create(name='مردانه')
        self.shirt = PriceItem.objects.create(category=men, name='پیراهن', dry_clean_price='220000')
        self.coat = PriceItem.objects.create(category=men, name='کاپشن', dry_clean_price='')
        Wallet.objects.create(customer=self.customer, balance=Decimal('5000000'))
        self.client = login_customer(Client(), self.customer)

    def place(self, *price_items, use_wallet=False):
        payload = {'items': [{'line_id': p.id, 'quantity': 1} for p in price_items], 'use_wallet': use_wallet}
        data = self.client.post(reverse('place_order'), json.dumps(payload), content_type='application/json').json()
        return data, Order.objects.get(id=data['order_id'])

    def card(self, order):
        return self.client.get(reverse('home'), {'order_id': order.id}).content.decode()

    def pay_link(self, order):
        return f'href="{reverse("request_payment", args=[order.id])}"'

    def test_fully_priced_order_can_be_paid_right_away(self):
        data, order = self.place(self.shirt)
        self.assertFalse(data['price_pending'])
        self.assertTrue(order.payment_open)
        self.assertIn(self.pay_link(order), self.card(order))

    def test_mixed_order_is_not_paid_from_wallet_at_checkout(self):
        data, order = self.place(self.shirt, self.coat, use_wallet=True)
        self.assertTrue(data['price_pending'])
        self.assertFalse(data['paid_by_wallet'])
        order.refresh_from_db()
        self.assertFalse(order.is_paid)
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('5000000'))

    def test_payment_locked_until_ready_and_priced(self):
        _, order = self.place(self.shirt, self.coat)
        self.assertFalse(order.payment_open)
        page = self.card(order)
        self.assertNotIn(self.pay_link(order), page)
        self.assertIn('پرداخت بعد از قیمت‌گذاری', page)

        # Neither payment route works before the order is ready.
        self.client.post(reverse('wallet_pay_order', args=[order.id]))
        response = self.client.get(reverse('request_payment', args=[order.id]))
        self.assertRedirects(response, f"{reverse('home')}?order_id={order.id}#track-section", fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertFalse(order.is_paid)

        # Priced while washing: the total is known but payment still waits for «ready».
        coat_line = order.orderitem_set.get(price=0)
        coat_line.price = 400000
        coat_line.save()
        order.refresh_from_db()
        self.assertFalse(order.payment_open)
        self.assertIn('مبلغ نهایی مشخص شد', self.card(order))

        order.status = 'ready'
        order.save()
        self.assertTrue(order.payment_open)
        self.assertIn(self.pay_link(order), self.card(order))
        self.client.post(reverse('wallet_pay_order', args=[order.id]))
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('5000000') - order.total_price)

    def test_ready_order_with_a_line_still_unpriced_stays_locked(self):
        _, order = self.place(self.shirt, self.coat)
        order.status = 'ready'
        order.save()
        self.assertTrue(order.has_unpriced_items)
        self.assertFalse(order.payment_open)
        self.assertIn('فروشگاه در حال ثبت قیمت نهایی', self.card(order))
        self.client.post(reverse('wallet_pay_order', args=[order.id]))
        order.refresh_from_db()
        self.assertFalse(order.is_paid)

    def test_panel_warns_when_unpriced_order_is_marked_ready(self):
        from django.contrib.auth import get_user_model
        _, order = self.place(self.shirt, self.coat)
        staff = Client()
        staff.force_login(get_user_model().objects.create_user('pending-staff', password='x', is_staff=True))
        response = staff.post(reverse('panel_order_status', args=[order.id]), {'status': 'ready'}, follow=True)
        self.assertContains(response, 'مشتری نمی‌تواند این فاکتور را پرداخت کند')


class HomeMessagesTests(TestCase):
    def test_flash_messages_render_on_home(self):
        customer = Customer.objects.create(name='پیام', phone='09120000018')
        order = Order.objects.create(customer=customer, total_price=Decimal('50000'))
        Wallet.objects.create(customer=customer, balance=Decimal('0'))
        client = login_customer(Client(), customer)
        response = client.post(reverse('wallet_pay_order', args=[order.id]), follow=True)
        self.assertContains(response, 'flash-msg')
        self.assertContains(response, 'موجودی کیف پول کافی نیست')


class ShopContactTests(TestCase):
    def test_contact_links_and_no_blocking_map(self):
        from .models import ShopSettings
        from .templatetags.fa_format import tel_digits, toman, fa_digits
        self.assertEqual(tel_digits('۰۹۱۲-۳۲۷۷۸۸۱'), '09123277881')
        self.assertEqual(toman(1250000), '۱٬۲۵۰٬۰۰۰')
        self.assertEqual(toman('abc'), 'abc')
        self.assertEqual(fa_digits(45), '۴۵')
        ShopSettings.load()
        page = Client().get(reverse('home')).content.decode()
        self.assertIn('href="tel:09123277881"', page)
        self.assertNotIn('<iframe', page)


class WalletPayMethodTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='پرداخت', phone='09120000019')
        self.wallet = Wallet.objects.create(customer=self.customer, balance=Decimal('100000'))
        self.order = Order.objects.create(customer=self.customer, total_price=Decimal('25000'))
        self.client = login_customer(Client(), self.customer)

    def test_get_never_spends_money(self):
        self.client.get(reverse('wallet_pay_order', args=[self.order.id]))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100000'))

    def test_double_post_pays_once(self):
        url = reverse('wallet_pay_order', args=[self.order.id])
        self.client.post(url)
        self.client.post(url)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('75000'))
        self.assertEqual(WalletTransaction.objects.filter(order=self.order).count(), 1)

    def test_logout_requires_post(self):
        self.client.get(reverse('customer_logout'))
        self.assertTrue(self.client.session.get('customer_logged_in'))
        self.client.post(reverse('customer_logout'))
        self.assertFalse(self.client.session.get('customer_logged_in'))


class GatewayPaymentTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='درگاه', phone='09120000020')
        self.order = Order.objects.create(customer=self.customer, total_price=Decimal('660000'))
        self.other_order = Order.objects.create(customer=self.customer, total_price=Decimal('660000'))
        self.client = login_customer(Client(), self.customer)

    def zarinpal(self, data):
        from unittest import mock
        response = mock.Mock(status_code=200, content=b'1')
        response.json.return_value = {'data': data, 'errors': []}
        return mock.patch('orders.views.requests.post', return_value=response)

    def test_guest_and_other_customer_cannot_start_payment(self):
        self.assertIn(reverse('customer_login'), Client().get(reverse('request_payment', args=[self.order.id]))['Location'])
        other = login_customer(Client(), Customer.objects.create(name='دیگری', phone='09120000021'))
        self.assertEqual(other.get(reverse('request_payment', args=[self.order.id])).status_code, 404)

    def test_full_payment_and_cancel(self):
        with self.zarinpal({'code': 100, 'authority': 'AUTH-1'}):
            response = self.client.get(reverse('request_payment', args=[self.order.id]))
        self.assertIn('StartPay/AUTH-1', response['Location'])
        cancel = self.client.get(reverse('verify_payment'), {'order_id': self.order.id, 'Authority': 'AUTH-1', 'Status': 'NOK'}, follow=True)
        self.assertContains(cancel, 'پرداخت لغو شد')
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)
        with self.zarinpal({'code': 100, 'ref_id': 999}):
            done = self.client.get(reverse('verify_payment'), {'order_id': self.order.id, 'Authority': 'AUTH-1', 'Status': 'OK'}, follow=True)
        self.assertContains(done, 'با موفقیت انجام شد')
        self.assertNotContains(done, 'phone=')
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)

    def test_reused_authority_cannot_pay_another_order(self):
        with self.zarinpal({'code': 100, 'authority': 'AUTH-2'}):
            self.client.get(reverse('request_payment', args=[self.order.id]))
        with self.zarinpal({'code': 101, 'ref_id': 1}):
            self.client.get(reverse('verify_payment'), {'order_id': self.other_order.id, 'Authority': 'AUTH-2', 'Status': 'OK'})
            self.client.get(reverse('verify_payment'), {'order_id': self.order.id, 'Authority': 'AUTH-2', 'Status': 'OK'})
        self.other_order.refresh_from_db()
        self.order.refresh_from_db()
        self.assertFalse(self.other_order.is_paid)
        self.assertTrue(self.order.is_paid)

    def test_gateway_down_shows_persian_message(self):
        from unittest import mock
        import requests as req
        with mock.patch('orders.views.requests.post', side_effect=req.exceptions.ConnectionError('boom')):
            response = self.client.get(reverse('request_payment', args=[self.order.id]), follow=True)
        self.assertContains(response, 'ارتباط با درگاه پرداخت برقرار نشد')
        self.assertNotContains(response, 'boom')


class WalletTopUpTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='شارژ', phone='09120000022')
        self.wallet = Wallet.objects.create(customer=self.customer, balance=Decimal('0'))
        self.client = login_customer(Client(), self.customer)

    def test_parse_toman_amount(self):
        from .views import parse_toman_amount
        cases = {'50000': 50000, '۵۰٬۰۰۰': 50000, '500,000': 500000, '500.000': 500000, ' 20,000 ': 20000,
                 '1.000.000': 1000000, '10000.5': None, '15000.50': None, 'abc': None, '-50000': None, '': None, '1e6': None}
        for raw, expected in cases.items():
            self.assertEqual(parse_toman_amount(raw), expected, raw)

    def test_invalid_amounts_never_reach_gateway(self):
        from unittest import mock
        with mock.patch('orders.views.requests.post') as post:
            for amount in ['10000.5', '9999', '0', 'abc', '60000000']:
                self.client.post(reverse('recharge_wallet'), {'amount': amount})
            post.assert_not_called()
        self.assertFalse(WalletTransaction.objects.exists())

    def test_unpaid_topups_are_not_shown_as_credit(self):
        from datetime import timedelta
        from django.utils import timezone
        old = WalletTransaction.objects.create(wallet=self.wallet, transaction_type='credit', amount=Decimal('1500050'), authority='A-old')
        WalletTransaction.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=2))
        WalletTransaction.objects.create(wallet=self.wallet, transaction_type='credit', amount=Decimal('20000'), authority='A-new')
        WalletTransaction.objects.create(wallet=self.wallet, transaction_type='credit', amount=Decimal('30000'), authority='A-ok', reference_id='1')
        page = self.client.get(reverse('wallet')).content.decode()
        self.assertIn('پرداخت نشد', page)
        self.assertIn('در انتظار پرداخت', page)
        self.assertIn('+۳۰٬۰۰۰', page)
        self.assertNotIn('+۱٬۵۰۰٬۰۵۰', page)
        self.assertNotIn('+۲۰٬۰۰۰', page)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CustomerAuthTests(TestCase):
    def setUp(self):
        from django.contrib.auth.hashers import make_password
        from django.core.cache import cache
        cache.clear()
        self.customer = Customer.objects.create(name='ورود', phone='09120000023', password_hash=make_password('right-password'))

    def login(self, password, phone='09120000023', next_url=None, client=None):
        data = {'phone': phone, 'password': password}
        if next_url:
            data['next'] = next_url
        return (client or Client()).post(reverse('customer_login'), data)

    def test_login_redirects_back_to_next(self):
        response = Client().get(reverse('wallet'))
        self.assertIn('next=/wallet/', response['Location'])
        response = self.login('right-password', next_url='/wallet/')
        self.assertEqual(response['Location'], '/wallet/')
        response = self.login('right-password', next_url='https://evil.example/')
        self.assertEqual(response['Location'], '/')

    def test_persian_digit_phone_logs_in(self):
        self.assertEqual(self.login('right-password', phone='۰۹۱۲ ۰۰۰ ۰۰۲۳').status_code, 302)

    def test_lockout_after_five_failures(self):
        for i in range(5):
            self.assertContains(self.login(f'wrong-{i}'), 'صحیح نیست')
        response = self.login('right-password')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '۱۵ دقیقه')

    def test_register_messages_for_existing_numbers(self):
        response = Client().post(reverse('customer_register'), {'name': 'تکراری', 'phone': '09120000023', 'password': 'abcdefgh'})
        self.assertContains(response, 'وارد حساب شوید')
        Customer.objects.create(name='حضوری', phone='09120000024')
        response = Client().post(reverse('customer_register'), {'name': 'حضوری', 'phone': '0912 000 0024', 'password': 'abcdefgh'})
        self.assertContains(response, 'با فروشگاه تماس بگیرید')
        self.assertNotContains(response, 'فعال‌سازی حساب قدیمی استفاده کنید')
        response = Client().post(reverse('customer_register'), {'name': 'ن' * 101, 'phone': '09120000025', 'password': 'abcdefgh'})
        self.assertContains(response, 'حداکثر')

    def test_phone_change_needs_current_password(self):
        client = login_customer(Client(), self.customer)
        client.post(reverse('account'), {'form_type': 'profile', 'name': 'ورود', 'phone': '09120000026'})
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, '09120000023')
        client.post(reverse('account'), {'form_type': 'profile', 'name': 'ورود', 'phone': '09120000026', 'current_password': 'right-password'})
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, '09120000026')

    def test_panel_order_for_walk_in_customer_reuses_normalized_phone(self):
        staff = get_user_model().objects.create_user('auth-staff', password='x', is_staff=True)
        client = Client()
        client.force_login(staff)
        client.post(reverse('panel_order_create'), {
            'new_customer_name': 'حضوری', 'new_customer_phone': '0912 000 0023',
            'item_name[]': ['پیراهن'], 'item_qty[]': ['1'], 'item_price[]': ['220000'],
        })
        self.assertEqual(Customer.objects.filter(phone__contains='0023').count(), 1)
        self.assertEqual(Order.objects.get().customer, self.customer)


class NoStoreTests(TestCase):
    def test_personal_pages_are_not_cached(self):
        customer = Customer.objects.create(name='کش', phone='09120000027')
        client = login_customer(Client(), customer)
        for url in [reverse('home'), reverse('account'), reverse('wallet')]:
            self.assertIn('no-store', client.get(url)['Cache-Control'], url)
        self.assertNotIn('no-store', Client().get(reverse('pricing')).get('Cache-Control', ''))


class ReviewTests(TestCase):
    def setUp(self):
        from .models import OrderReview
        self.OrderReview = OrderReview
        self.customer = Customer.objects.create(name='نظر دهنده', phone='09120000028')
        self.order = Order.objects.create(customer=self.customer, status='delivered', total_price=Decimal('1000'))
        self.client = login_customer(Client(), self.customer)

    def post(self, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload)
        return self.client.post(reverse('submit_review'), body, content_type='application/json')

    def test_malformed_input_is_400_not_500(self):
        for payload, raw in [(None, '[]'), (None, '{bad'), ({'order_id': 'abc', 'rating': 3}, None),
                             ({'order_id': self.order.id, 'rating': 4.9}, None),
                             ({'order_id': self.order.id, 'rating': 0}, None),
                             ({'order_id': self.order.id, 'rating': 6}, None),
                             ({'order_id': self.order.id, 'rating': True}, None)]:
            response = self.post(payload, raw)
            self.assertIn(response.status_code, (400, 404), (payload, raw))
        self.assertFalse(self.OrderReview.objects.exists())

    def test_text_review_waits_for_approval(self):
        data = self.post({'order_id': self.order.id, 'rating': 5, 'comment': '<script>alert(1)</script> عالی', 'tags': ['quality', 'x']}).json()
        self.assertTrue(data['pending_approval'])
        page = Client().get(reverse('home')).content.decode()
        self.assertNotIn('alert(1)', page)
        review = self.OrderReview.objects.get()
        self.assertEqual(review.tags, 'quality')
        review.is_hidden = False
        review.save()
        page = Client().get(reverse('home')).content.decode()
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        self.assertEqual(self.post({'order_id': self.order.id, 'rating': 1}).status_code, 400)

    def test_rating_only_review_counts_immediately(self):
        data = self.post({'order_id': self.order.id, 'rating': '4', 'tags': 5}).json()
        self.assertFalse(data['pending_approval'])
        self.assertEqual(self.OrderReview.objects.get().tags, '')


class ErrorPageTests(TestCase):
    def test_404_is_persian_and_hides_internals(self):
        response = Client().get('/blabla/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'این صفحه پیدا نشد', status_code=404)
        self.assertNotContains(response, 'URLconf', status_code=404)

    def test_static_files_are_served_with_debug_off(self):
        # The live site runs with DEBUG off; WhiteNoise must still serve CSS/images/icons.
        response = Client().get('/static/pwa/icon-192.png')
        self.assertEqual(response.status_code, 200)


class PanelValidationTests(TestCase):
    def setUp(self):
        staff = get_user_model().objects.create_user('panel-staff', password='x', is_staff=True)
        self.client = Client()
        self.client.force_login(staff)
        self.customer = Customer.objects.create(name='پنل', phone='09120000029')
        self.order = Order.objects.create(customer=self.customer)

    def test_bad_item_numbers_do_not_crash(self):
        url = reverse('panel_order_detail', args=[self.order.id])
        for qty, price in [('2.5', '1000'), ('abc', '1000'), ('0', '1000'), ('99999', '220000'), ('1', '-5'), ('1', '1e9')]:
            response = self.client.post(url, {'item_name': 'کت', 'item_qty': qty, 'item_price': price})
            self.assertEqual(response.status_code, 302, (qty, price))
        self.assertEqual(self.order.orderitem_set.count(), 0)
        self.client.post(url, {'item_name': 'کت', 'item_qty': '۲', 'item_price': '۱۰۰٬۰۰۰'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.total_price, Decimal('200000'))
        self.assertEqual(self.client.get(reverse('panel_orders')).status_code, 200)

    def test_create_order_rejects_bad_rows_without_leftovers(self):
        before = Order.objects.count()
        self.client.post(reverse('panel_order_create'), {
            'customer_id': self.customer.id,
            'item_name[]': ['پیراهن', 'کت'], 'item_qty[]': ['1', '2.5'], 'item_price[]': ['220000', '100000'],
        })
        self.assertEqual(Order.objects.count(), before)

    def test_next_redirect_stays_on_site(self):
        response = self.client.post(reverse('panel_order_status', args=[self.order.id]), {'status': 'washing', 'next': 'https://evil.example/'})
        self.assertEqual(response['Location'], reverse('panel_order_detail', args=[self.order.id]))
        response = self.client.post(reverse('panel_order_status', args=[self.order.id]), {'status': 'washing', 'next': '/panel/orders/'})
        self.assertEqual(response['Location'], '/panel/orders/')

    def test_invalid_coordinates_hidden_from_map_links(self):
        self.order.courier_requested = True
        self.order.latitude, self.order.longitude = 'nan', '51'
        self.order.save()
        page = self.client.get(reverse('panel_courier')).content.decode()
        self.assertNotIn('maps?q=nan', page)
        self.assertEqual(self.order.pickup_map_point, '')


class PanelSmokeTests(TestCase):
    def test_every_panel_page_renders(self):
        from .models import OrderItem, OrderReview, PriceCategory, PriceItem
        staff = get_user_model().objects.create_user('smoke-staff', password='x', is_staff=True)
        client = Client()
        client.force_login(staff)
        customer = Customer.objects.create(name='دود', phone='09120000030')
        order = Order.objects.create(customer=customer, status='delivered', courier_requested=True, latitude='35.7', longitude='51.3')
        OrderItem.objects.create(order=order, item_name='کت', quantity=1, price=Decimal('1000'))
        OrderReview.objects.create(order=order, customer=customer, rating=5, comment='خوب')
        PriceItem.objects.create(category=PriceCategory.objects.create(name='مردانه'), name='کت', dry_clean_price='1000')
        for name, args in [('panel_dashboard', []), ('panel_orders', []), ('panel_order_create', []),
                           ('panel_order_detail', [order.id]), ('panel_customers', []), ('panel_customer_detail', [customer.id]),
                           ('panel_pricing', []), ('panel_courier', []), ('panel_reviews', []), ('panel_settings', []),
                           ('print_receipt', [order.id])]:
            self.assertEqual(client.get(reverse(name, args=args)).status_code, 200, name)


class PricingPageTests(TestCase):
    def test_both_prices_and_search_on_all_screens(self):
        from .models import PriceCategory, PriceItem
        category = PriceCategory.objects.create(name='مردانه')
        PriceItem.objects.create(category=category, name='کت و شلوار', dry_clean_price='585000', iron_only_price='380000')
        page = Client().get(reverse('pricing')).content.decode()
        self.assertIn('۳۸۰٬۰۰۰', page)
        self.assertIn('۵۸۵٬۰۰۰', page)
        self.assertNotIn('.iron-value{display:none}', page)
        self.assertIn('id="price-search"', page)
        self.assertIn(f'id="cat-{category.id}"', page)
