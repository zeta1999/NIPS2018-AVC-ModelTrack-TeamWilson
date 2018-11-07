import cleverhans
from cleverhans.model import Model
class MadryEtAl_KLloss(cleverhans.attacks.MadryEtAl):
    def __init__(self, model, back='tf', sess=None, dtypestr='float32'):
        if not isinstance(model, Model):
            model = CallableModelWrapper(model, 'probs')

        super(MadryEtAl_KLloss, self).__init__(model, back, sess, dtypestr)
        self.feedable_kwargs = {'eps': self.np_dtype,
                                'clip_min': self.np_dtype,
                                'clip_max': self.np_dtype}
        self.structural_kwargs = ["loss_type", "nb_iter"]

    def parse_params(self, **kwargs):
        super(MadryEtAl_KLloss, self).parse_params(**kwargs)
        self.loss_type = kwargs.get("loss_type", "multinomial")
        assert self.loss_type in {"gaussian", "multinomial"}
        print("kl loss type: ", self.loss_type)
        return True

    def KL(self, p, q):
        import tensorflow as tf
        if self.loss_type == "gaussian":
            # the output distribution is treated as multi-dimensional gaussian with same std
            return tf.reduce_sum((p - q) ** 2, axis=-1)
        else: # KL of multinomial
            # the output distribution is treated as a single multinomial dist
            return tf.reduce_sum(p * (tf.log(p + 1e-10) - tf.log(q + 1e-10)), axis=-1)

    def attack(self, x, y):
        """
        This method creates a symbolic graph that given an input image,
        first randomly perturbs the image. The
        perturbation is bounded to an epsilon ball. Then multiple steps of
        gradient descent is performed to increase the probability of a target
        label or decrease the probability of the ground-truth label.

        :param x: A tensor with the input image.
        """
        import tensorflow as tf
        from cleverhans.utils_tf import clip_eta

        eta = tf.random_normal(tf.shape(x), 0, 1, dtype=self.tf_dtype)
        eta = eta / tf.norm(eta, ord=2) * self.eps

        x_p = tf.stop_gradient(tf.nn.softmax(self.model.get_logits(x)))
        for i in range(self.nb_iter):
            eta = self.attack_single_step(x, eta, x_p) # do not need y
        adv_x = x + eta
        return adv_x

    def attack_single_step(self, x, eta, x_p):
        """
        Given the original image and the perturbation computed so far, computes
        a new perturbation.

        :param x: A tensor with the original input.
        :param eta: A tensor the same shape as x that holds the perturbation.
        :param y: A tensor with the target labels or ground-truth labels.
        """
        import tensorflow as tf
        from cleverhans.utils_tf import clip_eta
        from cleverhans.loss import attack_softmax_cross_entropy

        adv_x = x + eta
        logits = self.model.get_logits(adv_x)
        loss = self.KL(x_p, tf.nn.softmax(logits))
        grad, = tf.gradients(loss, adv_x)
        eta = grad / tf.norm(grad, ord=2) * self.eps
        if self.clip_min is not None and self.clip_max is not None:
            adv_x = tf.clip_by_value(x + eta, self.clip_min, self.clip_max)
            eta = adv_x - x
        return eta

class MadryEtAl_L2(cleverhans.attacks.MadryEtAl):
    # ord only decide use linf or l2 to clip
    def attack_single_step(self, x, eta, y):
        """
        Given the original image and the perturbation computed so far, computes
        a new perturbation.

        :param x: A tensor with the original input.
        :param eta: A tensor the same shape as x that holds the perturbation.
        :param y: A tensor with the target labels or ground-truth labels.
        """
        import tensorflow as tf
        from cleverhans.utils_tf import clip_eta
        from cleverhans.loss import attack_softmax_cross_entropy

        adv_x = x + eta
        logits = self.model.get_logits(adv_x)
        loss = attack_softmax_cross_entropy(y, logits)
        if self.targeted:
            loss = -loss
        grad, = tf.gradients(loss, adv_x)
        axis = list(range(1, len(grad.shape)))
        scaled_signed_grad = self.eps_iter * grad / tf.sqrt(tf.reduce_mean(tf.square(grad), axis, keep_dims=True))
        adv_x = adv_x + scaled_signed_grad
        if self.clip_min is not None and self.clip_max is not None:
            adv_x = tf.clip_by_value(adv_x, self.clip_min, self.clip_max)
        eta = adv_x - x
        eta = clip_eta(eta, self.ord, self.eps) # by default: use linf to clip
        return eta

class MadryEtAl_transfer(cleverhans.attacks.MadryEtAl):
    def __init__(self, model, transfer, back="tf", sess=None, dtypestr="float32"):
        super(MadryEtAl_transfer, self).__init__(model, back=back, sess=sess, dtypestr=dtypestr)
        self.transfer_model = transfer

    def attack_single_step(self, x, eta, y):
        """
        Given the original image and the perturbation computed so far, computes
        a new perturbation.

        :param x: A tensor with the original input.
        :param eta: A tensor the same shape as x that holds the perturbation.
        :param y: A tensor with the target labels or ground-truth labels.
        """
        import tensorflow as tf
        from cleverhans.utils_tf import clip_eta
        from cleverhans.loss import attack_softmax_cross_entropy

        adv_x = x + eta
        logits = self.model.get_logits(adv_x)
        transfer_logits = self.transfer_model.get_logits(adv_x)
        transfer_loss = attack_softmax_cross_entropy(y, transfer_logits)
        if self.targeted:
            loss = -loss
        grad, = tf.gradients(transfer_loss, adv_x)
        scaled_signed_grad = self.eps_iter * tf.sign(grad)
        adv_x = adv_x + scaled_signed_grad
        if self.clip_min is not None and self.clip_max is not None:
            adv_x = tf.clip_by_value(adv_x, self.clip_min, self.clip_max)
        eta = adv_x - x
        eta = clip_eta(eta, self.ord, self.eps)
        return eta